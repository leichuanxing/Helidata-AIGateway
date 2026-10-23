export const configurationTabs=['brand','basic','performance','vector','elasticsearch','status']
export function settingsTab(role:string|undefined,desired:unknown){
  const allowed=role==='super_admin'?[...configurationTabs,'backups','audit']:role==='admin'?['audit']:[]
  return typeof desired==='string'&&allowed.includes(desired)?desired:allowed[0]||''
}
export function isConfigurationTab(tab:string){return configurationTabs.includes(tab)}

// Preserve links saved before governance configuration moved to its modules.
export function legacySettingsDestination(tab:unknown){return tab==='smart'?'/admin/smart-route/configs':tab==='compliance'?'/admin/compliance/policies':null}
