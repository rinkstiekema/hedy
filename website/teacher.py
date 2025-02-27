import json
from flask_babel import gettext
import hedy
import hedyweb
from website.auth import requires_login, is_teacher, is_admin, current_user, validate_student_signup_data, store_new_student_account
import utils
import uuid
from flask import g, request, jsonify, redirect, session
from flask_helpers import render_template
import os
import hedy_content
from config import config

cookie_name = config['session']['cookie_name']
invite_length = config['session']['invite_length'] * 60


def routes(app, database, achievements):
    global DATABASE
    global ACHIEVEMENTS
    DATABASE = database
    ACHIEVEMENTS = achievements

    @app.route('/for-teachers', methods=['GET'])
    @requires_login
    def for_teachers_page(user):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('not_teacher'))

        welcome_teacher = session.get('welcome-teacher') or False
        session.pop('welcome-teacher', None)

        teacher_classes = DATABASE.get_teacher_classes(current_user()['username'], True)
        adventures = []
        for adventure in DATABASE.get_teacher_adventures(current_user()['username']):
            adventures.append(
                {'id': adventure.get('id'),
                 'name': adventure.get('name'),
                 'date': utils.localized_date_format(adventure.get('date')),
                 'level': adventure.get('level')
                 }
            )

        return render_template('for-teachers.html', current_page='my-profile', page_title=gettext('title_for-teacher'),
                               teacher_classes=teacher_classes,
                               teacher_adventures=adventures, welcome_teacher=welcome_teacher)


    @app.route('/for-teachers/manual', methods=['GET'])
    @requires_login
    def get_teacher_manual(user):
        page_translations = hedyweb.PageTranslations('for-teachers').get_page_translations(g.lang)
        return render_template('teacher-manual.html', current_page='my-profile', content=page_translations)


    @app.route('/classes', methods=['GET'])
    @requires_login
    def get_classes(user):
        if not is_teacher(user):
            return utils.error_page_403(error=403, ui_message=gettext('retrieve_class_error'))
        return jsonify (DATABASE.get_teacher_classes(user['username'], True))

    @app.route('/for-teachers/class/<class_id>', methods=['GET'])
    @requires_login
    def get_class(user, class_id):
        app.logger.info('This is info output')
        if not is_teacher(user) and not is_admin(user):
            return utils.error_page_403(error=403, ui_message=gettext('retrieve_class_error'))
        Class = DATABASE.get_class(class_id)
        if not Class or (Class['teacher'] != user['username'] and not is_admin(user)):
            return utils.error_page(error=404, ui_message=gettext('no_such_class'))
        students = []

        for student_username in Class.get('students', []):
            student = DATABASE.user_by_username(student_username)
            programs = DATABASE.programs_for_user(student_username)
            highest_level = max(program['level'] for program in programs) if len(programs) else 0
            students.append({
                'username': student_username,
                'last_login': student['last_login'],
                'programs': len(programs),
                'highest_level': highest_level
            })

        # Sort the students by their last login
        students = sorted(students, key=lambda d: d.get('last_login', 0), reverse=True)
        # After sorting: replace the number value by a string format date
        for student in students:
            student['last_login'] = utils.localized_date_format(student.get('last_login', 0))

        if utils.is_testing_request(request):
            return jsonify({'students': students, 'link': Class['link'], 'name': Class['name'], 'id': Class['id']})

        achievement = None
        if len(students) > 20:
            achievement = ACHIEVEMENTS.add_single_achievement(user['username'], "full_house")
        if achievement:
            achievement = json.dumps(achievement)

        invites = []
        for invite in DATABASE.get_class_invites(Class['id']):
            invites.append({'username': invite['username'],
                            'timestamp': utils.localized_date_format(invite['timestamp'], short_format=True),
                            'expire_timestamp': utils.localized_date_format(invite['ttl'], short_format=True)})

        return render_template('class-overview.html', current_page='my-profile',
                                page_title=gettext('title_class-overview'),
                                achievement=achievement, invites=invites,
                                class_info={'students': students, 'link': os.getenv('BASE_URL') + '/hedy/l/' + Class['link'],
                                            'name': Class['name'], 'id': Class['id']})

    @app.route('/class', methods=['POST'])
    @requires_login
    def create_class(user):
        if not is_teacher(user):
            return gettext('only_teacher_create_class'), 403

        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('name'), str):
            return gettext('class_name_invalid'), 400
        if len(body.get('name')) < 1:
            return gettext('class_name_empty'), 400

        # We use this extra call to verify if the class name doesn't already exist, if so it's a duplicate
        Classes = DATABASE.get_teacher_classes(user['username'], True)
        for Class in Classes:
            if Class['name'] == body['name']:
                return gettext('class_name_duplicate'), 200

        Class = {
            'id': uuid.uuid4().hex,
            'date': utils.timems(),
            'teacher': user['username'],
            'link': utils.random_id_generator(7),
            'name': body['name']
        }

        DATABASE.store_class(Class)
        achievement = ACHIEVEMENTS.add_single_achievement(user['username'], "ready_set_education")
        if achievement:
            return {'id': Class['id'], 'achievement': achievement}, 200
        return {'id': Class['id']}, 200

    @app.route('/class/<class_id>', methods=['PUT'])
    @requires_login
    def update_class(user, class_id):
        if not is_teacher(user):
            return 'Only teachers can update classes', 403

        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('name'), str):
            return gettext('class_name_invalid'), 400
        if len(body.get('name')) < 1:
            return gettext('class_name_empty'), 400

        Class = DATABASE.get_class (class_id)
        if not Class or Class['teacher'] != user['username']:
            return gettext('no_such_class'), 404

        # We use this extra call to verify if the class name doesn't already exist, if so it's a duplicate
        Classes = DATABASE.get_teacher_classes(user['username'], True)
        for Class in Classes:
            if Class['name'] == body['name']:
                return "duplicate", 200 # Todo TB: Will have to look into this, but not sure why we return a 200?

        DATABASE.update_class(class_id, body['name'])
        achievement = ACHIEVEMENTS.add_single_achievement(user['username'], "on_second_thoughts")
        if achievement:
            return {'achievement': achievement}, 200
        return {}, 200

    @app.route('/class/<class_id>', methods=['DELETE'])
    @requires_login
    def delete_class(user, class_id):
        Class = DATABASE.get_class(class_id)
        if not Class or Class['teacher'] != user['username']:
            return gettext('no_such_class'), 404

        DATABASE.delete_class(Class)
        achievement = ACHIEVEMENTS.add_single_achievement(user['username'], "end_of_semester")
        if achievement:
            return {'achievement': achievement}, 200
        return {}, 200

    @app.route('/duplicate_class', methods=['POST'])
    @requires_login
    def duplicate_class(user):
        if not is_teacher(user):
            return gettext('only_teacher_create_class'), 403

        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('name'), str):
            return gettext('class_name_invalid'), 400
        if len(body.get('name')) < 1:
            return gettext('class_name_empty'), 400

        Class = DATABASE.get_class(body.get('id'))
        if not Class or Class['teacher'] != user['username']:
            return gettext('no_such_class'), 404

        # We use this extra call to verify if the class name doesn't already exist, if so it's a duplicate
        # Todo TB: This is a duplicate function, might be nice to perform some clean-up to reduce these parts
        Classes = DATABASE.get_teacher_classes(user['username'], True)
        for Class in Classes:
            if Class['name'] == body.get('name'):
                return gettext('class_name_duplicate'), 400

        # All the class settings are still unique, we are only concerned with copying the customizations
        # Shortly: Create a class like normal: concern with copying the customizations
        class_id = uuid.uuid4().hex

        new_class = {
            'id': class_id,
            'date': utils.timems(),
            'teacher': user['username'],
            'link': utils.random_id_generator(7),
            'name': body.get('name')
        }

        DATABASE.store_class(new_class)

        # Get the customizations of the current class -> if they exist, update id and store again
        customizations = DATABASE.get_class_customizations(body.get('id'))
        if customizations:
            customizations['id'] = class_id
            DATABASE.update_class_customizations(customizations)

        achievement = ACHIEVEMENTS.add_single_achievement(current_user()['username'], "one_for_money")
        if achievement:
            return {'achievement': achievement}, 200


    @app.route('/class/<class_id>/prejoin/<link>', methods=['GET'])
    def prejoin_class(class_id, link):
        Class = DATABASE.get_class(class_id)
        if not Class or Class['link'] != link:
            return utils.error_page(error=404, ui_message=gettext('invalid_class_link'))
        if request.cookies.get(cookie_name):
            token = DATABASE.get_token(request.cookies.get(cookie_name))
            if token and token.get('username') in Class.get('students', []):
                    return render_template('class-prejoin.html', joined=True, page_title=gettext('title_join-class'),
                                            current_page='my-profile', class_info={'name': Class ['name']})
        return render_template('class-prejoin.html', joined=False, page_title=gettext('title_join-class'),
                               current_page='my-profile', class_info={'id': Class ['id'], 'name': Class ['name']})

    @app.route('/class/join', methods=['POST'])
    def join_class():
        body = request.json
        Class = None
        if 'id' in body:
            Class = DATABASE.get_class(body['id'])
        if not Class or Class['id'] != body['id']:
            return utils.error_page(error=404, ui_message=gettext('invalid_class_link'))

        if not current_user()['username']:
            return gettext('join_prompt'), 403

        DATABASE.add_student_to_class(Class['id'], current_user()['username'])
        # We only want to remove the invite if the user joins the class with an actual pending invite
        invite = DATABASE.get_username_invite(current_user()['username'])
        if invite and invite.get('class_id') == body['id']:
            DATABASE.remove_class_invite(current_user()['username'])
            # Also remove the pending message in this case
            session['messages'] = 0

        achievement = ACHIEVEMENTS.add_single_achievement(current_user()['username'], "epic_education")
        if achievement:
            return {'achievement': achievement}, 200
        return {}, 200

    @app.route('/class/<class_id>/student/<student_id>', methods=['DELETE'])
    @requires_login
    def leave_class(user, class_id, student_id):
        Class = DATABASE.get_class(class_id)
        if not Class or (Class['teacher'] != user['username'] and student_id != user['username']):
            return gettext('ajax_error'), 400

        DATABASE.remove_student_from_class(Class['id'], student_id)
        achievement = None
        if Class['teacher'] == user['username']:
            achievement = ACHIEVEMENTS.add_single_achievement(user['username'], "detention")
        if achievement:
            return {'achievement': achievement}, 200
        return {}, 200

    @app.route('/for-teachers/customize-class/<class_id>', methods=['GET'])
    @requires_login
    def get_class_info(user, class_id):
        if not is_teacher(user) and not is_admin(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_class_error'))
        Class = DATABASE.get_class(class_id)
        if not Class or (Class['teacher'] != user['username'] and not is_admin(user)):
            return utils.error_page(error=404, ui_message=gettext('no_such_class'))

        if hedy_content.Adventures(g.lang).has_adventures():
            adventures = hedy_content.Adventures(g.lang).get_adventure_keyname_name_levels()
        else:
            adventures = hedy_content.Adventures("en").get_adventure_keyname_name_levels()

        teacher_adventures = DATABASE.get_teacher_adventures(user['username'])
        customizations = DATABASE.get_class_customizations(class_id)

        return render_template('customize-class.html', page_title=gettext('title_customize-class'),
                               class_info={'name': Class['name'], 'id': Class['id']}, max_level=hedy.HEDY_MAX_LEVEL,
                               adventures=adventures, teacher_adventures=teacher_adventures,
                               customizations=customizations, current_page='my-profile')

    @app.route('/for-teachers/customize-class/<class_id>', methods=['DELETE'])
    @requires_login
    def delete_customizations(user, class_id):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_class_error'))
        Class = DATABASE.get_class(class_id)
        if not Class or Class['teacher'] != user['username']:
            return utils.error_page(error=404, ui_message=gettext('no_such_class'))

        DATABASE.delete_class_customizations(class_id)
        return {'success': gettext('customization_deleted')}, 200

    @app.route('/for-teachers/customize-class/<class_id>', methods=['POST'])
    @requires_login
    def update_customizations(user, class_id):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_class_error'))
        Class = DATABASE.get_class(class_id)
        if not Class or Class['teacher'] != user['username']:
            return utils.error_page(error=404, ui_message=gettext('no_such_class'))

        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('levels'), list):
            return "Levels must be a list", 400
        if not isinstance(body.get('adventures'), dict):
            return 'Adventures must be a dict', 400
        if not isinstance(body.get('teacher_adventures'), list):
            return 'Teacher adventures must be a list', 400
        if not isinstance(body.get('other_settings'), list):
            return 'Other settings must be a list', 400
        if not isinstance(body.get('opening_dates'), dict):
            return 'Opening dates must be a dict', 400

        # Values are always strings from the front-end -> convert to numbers
        levels = [int(i) for i in body['levels']]

        opening_dates = body['opening_dates'].copy()
        for level, timestamp in body.get('opening_dates').items():
            if len(timestamp) < 1:
                opening_dates.pop(level)
            else:
                try:
                    opening_dates[level] = utils.datetotimeordate(timestamp)
                except:
                    return 'One or more of your opening dates is invalid', 400

        adventures = {}
        for name, adventure_levels in body['adventures'].items():
            adventures[name] = [int(i) for i in adventure_levels]

        customizations = {
            'id': class_id,
            'levels': levels,
            'opening_dates': opening_dates,
            'adventures': adventures,
            'teacher_adventures': body['teacher_adventures'],
            'other_settings': body['other_settings']
        }

        DATABASE.update_class_customizations(customizations)
        return {'success': gettext('class_customize_success')}, 200

    @app.route('/invite_student', methods=['POST'])
    @requires_login
    def invite_student(user):
        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('username'), str):
            return gettext('username_invalid'), 400
        if not isinstance(body.get('class_id'), str):
            return 'class id must be a string', 400
        if len(body.get('username')) < 1:
            return gettext('username_empty'), 400

        username = body.get('username').lower()
        class_id = body.get('class_id')

        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_class_error'))
        Class = DATABASE.get_class(class_id)
        if not Class or Class['teacher'] != user['username']:
            return utils.error_page(error=404, ui_message=gettext('no_such_class'))

        user = DATABASE.user_by_username(username)
        if not user:
            return gettext('student_not_existing'), 400
        if 'students' in Class and user['username'] in Class['students']:
            return gettext('student_already_in_class'), 400
        if DATABASE.get_username_invite(user['username']):
            return gettext('student_already_invite'), 400

        # So: The class and student exist and are currently not a combination -> invite!
        data = {
            'username': username,
            'class_id': class_id,
            'timestamp': utils.times(),
            'ttl': utils.times() + invite_length
        }
        DATABASE.add_class_invite(data)
        return {}, 200

    @app.route('/remove_student_invite', methods=['POST'])
    @requires_login
    def remove_invite(user):
        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('username'), str):
            return gettext('username_invalid'), 400
        if not isinstance(body.get('class_id'), str):
            return 'class id must be a string', 400

        username = body.get('username')
        class_id = body.get('class_id')

        if not is_teacher(user) and username != user.get('username'):
            return utils.error_page(error=403, ui_message=gettext('retrieve_class_error'))
        Class = DATABASE.get_class(class_id)
        if not Class or (Class['teacher'] != user['username'] and username != user.get('username')):
            return utils.error_page(error=404, ui_message=gettext('no_such_class'))

        DATABASE.remove_class_invite(username)
        return {}, 200

    @app.route('/for-teachers/create-accounts/<class_id>', methods=['GET'])
    @requires_login
    def create_accounts(user, class_id):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('not_teacher'))
        current_class = DATABASE.get_class(class_id)
        if not current_class or current_class.get('teacher') != user.get('username'):
            return utils.error_page(error=403, ui_message=gettext('no_such_class'))

        return render_template('create-accounts.html', current_class = current_class)

    @app.route('/for-teachers/create-accounts', methods=['POST'])
    @requires_login
    def store_accounts(user):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('not_teacher'))
        body = request.json

        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('accounts'), list):
            return "accounts should be a list!", 400

        if len(body.get('accounts', [])) < 1:
            return gettext('no_accounts'), 400

        usernames = []

        # Validation for correct types and duplicates
        for account in body.get('accounts', []):
            validation = validate_student_signup_data(account)
            if validation:
                return validation, 400
            if account.get('username').strip().lower() in usernames:
                return {'error': gettext('unique_usernames'), 'value': account.get('username')}, 200
            usernames.append(account.get('username').strip().lower())

        # Validation for duplicates in the db
        classes = DATABASE.get_teacher_classes(user['username'], False)
        for account in body.get('accounts', []):
            if account.get('class') and account['class'] not in [i.get('name') for i in classes]:
                return "not your class", 404
            if DATABASE.user_by_username(account.get('username').strip().lower()):
                return {'error': gettext('usernames_exist'), 'value': account.get('username').strip().lower()}, 200

        # Now -> actually store the users in the db
        for account in body.get('accounts', []):
            # Set the current teacher language and keyword language as new account language
            account['language'] = g.lang
            account['keyword_language'] = g.keyword_lang
            store_new_student_account(account, user['username'])
            if account.get('class'):
                class_id = [i.get('id') for i in classes if i.get('name') == account.get('class')][0]
                DATABASE.add_student_to_class(class_id, account.get('username').strip().lower())
        return {'success': gettext('accounts_created')}, 200

    @app.route('/for-teachers/customize-adventure/view/<adventure_id>', methods=['GET'])
    @requires_login
    def view_adventure(user, adventure_id):
        if not is_teacher(user) and not is_admin(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_adventure_error'))
        adventure = DATABASE.get_adventure(adventure_id)
        if not adventure:
            return utils.error_page(error=404, ui_message=gettext('no_such_adventure'))
        if adventure['creator'] != user['username'] and not is_admin(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_adventure_error'))

        # Add level to the <pre> tag to let syntax highlighting know which highlighting we need!
        adventure['content'] = adventure['content'].replace("<pre>", "<pre class='no-copy-button' level='" + str(adventure['level']) + "'>")
        adventure['content'] = adventure['content'].format(**hedy_content.KEYWORDS.get(g.keyword_lang))

        return render_template('view-adventure.html', adventure=adventure,
                               page_title=gettext('title_view-adventure'), current_page='my-profile')

    @app.route('/for-teachers/customize-adventure/<adventure_id>', methods=['GET'])
    @requires_login
    def get_adventure_info(user, adventure_id):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_adventure_error'))
        adventure = DATABASE.get_adventure(adventure_id)
        if not adventure or adventure['creator'] != user['username']:
            return utils.error_page(error=404, ui_message=gettext('no_such_adventure'))

        # Now it gets a bit complex, we want to get the teacher classes as well as the customizations
        # This is a quite expensive retrieval, but we should be fine as this page is not called often
        # We only need the name, id and if it already has the adventure set as data to the front-end
        Classes = DATABASE.get_teacher_classes(user['username'])
        class_data = []
        for Class in Classes:
            temp = {'name': Class.get('name'), 'id': Class.get('id'), 'checked': False}
            customizations = DATABASE.get_class_customizations(Class.get('id'))
            if customizations and adventure_id in customizations.get('teacher_adventures', []):
                temp['checked'] = True
            class_data.append(temp)

        return render_template('customize-adventure.html', page_title=gettext('title_customize-adventure'),
                               adventure=adventure, class_data=class_data,
                               max_level=hedy.HEDY_MAX_LEVEL, current_page='my-profile')

    @app.route('/for-teachers/customize-adventure', methods=['POST'])
    @requires_login
    def update_adventure(user):
        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('id'), str):
            return gettext('adventure_id_invalid'), 400
        if not isinstance(body.get('name'), str):
            return gettext('adventure_name_invalid'), 400
        if not isinstance(body.get('level'), str):
            return gettext('level_invalid'), 400
        if not isinstance(body.get('content'), str):
            return gettext('content_invalid'), 400
        if len(body.get('content')) < 20:
            return gettext('adventure_length'), 400
        if not isinstance(body.get('public'), bool):
            return gettext('public_invalid'), 400
        if not isinstance(body.get('classes'), list):
            return gettext('classes_invalid'), 400

        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_adventure_error'))
        current_adventure = DATABASE.get_adventure(body['id'])
        if not current_adventure or current_adventure['creator'] != user['username']:
            return utils.error_page(error=404, ui_message=gettext('no_such_adventure'))

        adventures = DATABASE.get_teacher_adventures(user['username'])
        for adventure in adventures:
            if adventure['name'] == body['name'] and adventure['id'] != body['id']:
                return gettext('adventure_duplicate'), 400

        # We want to make sure the adventure is valid and only contains correct placeholders
        # Try to parse with our current language, if it fails -> return an error to the user
        try:
            body['content'].format(**hedy_content.KEYWORDS.get(g.keyword_lang))
        except:
            return gettext('something_went_wrong_keyword_parsing'), 400

        adventure = {
            'date': utils.timems(),
            'creator': user['username'],
            'name': body['name'],
            'level': body['level'],
            'content': body['content'],
            'public': body['public']
        }

        DATABASE.update_adventure(body['id'], adventure)

        # Once the adventure is correctly stored we have to update all class customizations
        # This is once again an expensive operation, we have to retrieve all teacher customizations
        # Then check if something is changed with the current situation, if so -> update in database
        Classes = DATABASE.get_teacher_classes(user['username'])
        for Class in Classes:
            # If so, the adventure should be in the class
            if Class.get('id') in body.get('classes', []):
                DATABASE.add_adventure_to_class_customizations(Class.get('id'), body.get('id'))
            else:
                DATABASE.remove_adventure_from_class_customizations(Class.get('id'), body.get('id'))

        return {'success': gettext('adventure_updated')}, 200

    @app.route('/for-teachers/customize-adventure/<adventure_id>', methods=['DELETE'])
    @requires_login
    def delete_adventure(user, adventure_id):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('retrieve_adventure_error'))
        adventure = DATABASE.get_adventure(adventure_id)
        if not adventure or adventure['creator'] != user['username']:
            return utils.error_page(error=404, ui_message=gettext('no_such_adventure'))

        DATABASE.delete_adventure(adventure_id)
        return {}, 200

    @app.route('/for-teachers/preview-adventure', methods=['POST'])
    def parse_preview_adventure():
        body = request.json
        try:
            code = body.get('code').format(**hedy_content.KEYWORDS.get(g.keyword_lang))
        except:
            return gettext('something_went_wrong_keyword_parsing'), 400
        return {'code': code}, 200

    @app.route('/for-teachers/create_adventure', methods=['POST'])
    @requires_login
    def create_adventure(user):
        if not is_teacher(user):
            return utils.error_page(error=403, ui_message=gettext('create_adventure'))

        body = request.json
        # Validations
        if not isinstance(body, dict):
            return gettext('ajax_error'), 400
        if not isinstance(body.get('name'), str):
            return gettext('adventure_name_invalid'), 400
        if len(body.get('name')) < 1:
            return gettext('adventure_empty'), 400

        adventures = DATABASE.get_teacher_adventures(user['username'])
        for adventure in adventures:
            if adventure['name'] == body['name']:
                return gettext('adventure_duplicate'), 400

        adventure = {
            'id': uuid.uuid4().hex,
            'date': utils.timems(),
            'creator': user['username'],
            'name': body['name'],
            'level': 1,
            'content': ""
        }

        DATABASE.store_adventure(adventure)
        return {'id': adventure['id']}, 200

    @app.route('/hedy/l/<link_id>', methods=['GET'])
    def resolve_class_link(link_id):
        Class = DATABASE.resolve_class_link(link_id)
        if not Class:
            return utils.error_page(error=404, ui_message=gettext('invalid_class_link'))
        return redirect(request.url.replace('/hedy/l/' + link_id, '/class/' + Class ['id'] + '/prejoin/' + link_id), code=302)
