/* Entry module for /activate. One import and one call: the page's behaviour lives in
   ../activation.js, and this file exists so the HTML names exactly one script. */

import { init } from "../activation.js?v=13";

init();
