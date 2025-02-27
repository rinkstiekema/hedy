/*** ADDING A TUTORIAL LEVEL SHORT GUIDE ***/

// Use this file as a template to create the tutorial for any level
// Create a dedicated file such as "level2.ts" and make sure you have startLevelX() and callNextStepLevelX() functions
// Add these to the startLevel() and callNextLevelStep() functions in tutorial.ts and make sure to import them correctly
// Also make sure that for every step/level combination there is an entry in the corresponding YAML file
// To start the tutorial for a specific level, for example level 1
// Call "startLevelTutorial(<level>)" on from a template, the rest should be handled automatically

import {tutorialPopup} from "./utils";

let current_step = 0;

export function startLevel1() {
  current_step = 1;
  $('#adventures').hide();

  tutorialPopup("1", current_step);
}

export function callNextStepLevel1() {
  // Do something

}