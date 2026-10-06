export type Provider={id:number;name:string;provider_type:string;protocol:string;base_url:string;proxy:string|null;priority:number;max_concurrency:number;status:string;health_status:string;scheduling_state:string;current_concurrency:number|null;failure_count:number;cooldown_until:string|null;remark:string;has_api_key:boolean;last_test_at:string|null;last_http_status:number|null;last_latency_ms:number|null;last_error_code:string|null;created_at:string;updated_at:string}
export type ProviderType={code:string;name:string;protocols:string[];base_url:string;key_required:boolean}
export type ProviderDraftMapping={logical_model:string;upstream_model:string;model_type:string;status:string}
export type TestResult={success:boolean;network_connected:boolean;authentication:string;http_status:number|null;latency_ms:number;model_count:number|null;error_code:string|null;message:string}
export const healthLabels:Record<string,string>={unknown:'未确认',healthy:'连接正常',unhealthy:'连接异常'}
export const authLabels:Record<string,string>={accepted:'请求被接受',not_configured:'未配置 Key',failed:'鉴权失败',unknown:'未确认'}

export const schedulingLabels:Record<string,string>={Available:'可用',Cooling:'冷却中',Unavailable:'不可用',Disabled:'已禁用'}
