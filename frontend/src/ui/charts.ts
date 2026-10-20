import {use,init,type EChartsType} from 'echarts/core'
import {LineChart,BarChart} from 'echarts/charts'
import {GridComponent,LegendComponent,TooltipComponent,DataZoomComponent,GraphicComponent,MarkLineComponent} from 'echarts/components'
import {CanvasRenderer} from 'echarts/renderers'
use([LineChart,BarChart,GridComponent,LegendComponent,TooltipComponent,DataZoomComponent,GraphicComponent,MarkLineComponent,CanvasRenderer])
export {init}
export type ECharts=EChartsType
