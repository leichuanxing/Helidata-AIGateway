export const configurationTabs=['brand','basic','performance','vector','smart','compliance','elasticsearch','status']
export function settingsTab(role:string|undefined,desired:unknown){
  const allowed=role==='super_admin'?[...configurationTabs,'backups','audit']:role==='admin'?['audit']:[]
  return typeof desired==='string'&&allowed.includes(desired)?desired:allowed[0]||''
}
export function isConfigurationTab(tab:string){return configurationTabs.includes(tab)}
