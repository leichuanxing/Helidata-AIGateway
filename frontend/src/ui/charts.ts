import {use,init,type EChartsType} from 'echarts/core'
import {LineChart,BarChart} from 'echarts/charts'
import {GridComponent,LegendComponent,TooltipComponent,DataZoomComponent,GraphicComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
use([LineChart,BarChart,GridComponent,LegendComponent,TooltipComponent,DataZoomComponent,GraphicComponent,CanvasRenderer])
export {init}
export type ECharts=EChartsType
