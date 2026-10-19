/** Stop scheduling billable requests after cancellation or stale configuration. */
export async function runProviderTests<T extends {error_code?:string|null}>(names:string[],signal:AbortSignal,request:(name:string,signal:AbortSignal)=>Promise<T[]>,onResults:(rows:T[])=>void){
  for(const name of names){
    if(signal.aborted)break
    const rows=await request(name,signal)
    if(signal.aborted)break
    onResults(rows)
    if(rows.some(row=>['PROVIDER_CHANGED','ADMIN_TEST_FORBIDDEN'].includes(row.error_code||'')))break
  }
}
