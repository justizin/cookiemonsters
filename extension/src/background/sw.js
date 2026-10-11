/* Chrome / Edge service-worker entry. Firefox and Safari load the same files
 * through background.scripts (see manifest overlays). */
importScripts('../common/generated_core.js', '../common/site.js', '../common/score.js', 'bg.js');
