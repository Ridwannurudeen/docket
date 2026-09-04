/* Entry module for /my-agents. One import and one call: the page's behaviour lives in
   ../jobs.js, and this file exists so the HTML names exactly one script. */

import { init } from "../jobs.js?v=13";

init();
