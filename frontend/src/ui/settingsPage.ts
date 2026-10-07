// Warm only component code, never cache editable settings or credentials.
export const settingsPage=()=>import('../views/Settings.vue')
export function warmSettingsPage(){void settingsPage().catch(()=>{})}
