# v1.9.2：地球与独立平台轨道

首页以本地地球影像纹理呈现大陆、海洋、云层视觉与大气光照。豆包、DeepSeek、Kimi、千问、腾讯元宝与知乎直答分别沿不同轨道运行，轨道倾角、速度与方向各有差异。节点使用各自的文字或字母徽标（不是官方商标图形），名称始终朝向读者；表面网络连线减弱，让陆地细节更清楚。

## 交互与空间

拖动场景或使用方向键同时调整地球和轨道视角；反向按钮切换轨道运行方向，暂停按钮停止自动运动，重置按钮恢复初始视角与轨道相位。鼠标移入或键盘聚焦卫星节点时暂停运动，便于读取与选择。系统设置“减少动画”时停止自动运动，用户仍可主动查看地球与平台状态。

选中的平台名称、状态和连接入口集中在球体下方的紧凑横条内，取代原先的大卡片。点击卫星节点只切换该条显示的连接状态，点击连接入口打开对应向导。窗口已打开、标定已保存与账号实际登录有效是不同状态，须以连接向导检查为准。

## 发起检查

1. 在首页填写实际问题，点击“选择平台并检查”，将问题带入任务弹窗。
2. 选择一个或多个平台，核对会话方式与实际发送内容。
3. 点击“创建并执行”后，才创建任务并交给本机执行器。

发送目标以任务弹窗中的勾选为准。点击卫星、旋转地球、暂停动画或打开连接向导均不会发送问题。网页与官方 API 分开记录，独立对话与连续会话分开统计。

## 场景与业务数据

地球纹理与轨道是本地视觉资源，不是实时卫星影像、气象或全球请求流量。六个平台在场景中的位置没有服务器地理含义，网络连线不表示问题已经发送。

本次更新不改动回答采集、名称命中、导出、回收站、每日计划和后台执行逻辑。自动校验针对问题对应关系与回答结束状态，不核实平台回答中的事实，也不把文字提及视为推荐排名。

功能与数据边界见 [README](../README.md#数据与统计边界)，记录导出与清理见[导出与回收站](records-export-and-trash.md)。

## 地球纹理与来源

表面纹理使用 NASA Earth Observatory 的 [Blue Marble: Next Generation，地形与海底地形版本](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/)，选取2004年7月的历史合成影像。本机资源为 `static/globe-earth.jpg`，来源与使用说明随包保存在 `static/globe-earth-LICENSE.txt`；运行时不请求 NASA 网站或外部 CDN。

图像来源署名为 NASA Earth Observatory。使用说明参考 [NASA Earth 图像常见问题](https://science.nasa.gov/earth/faq/)与 [NASA 图像和媒体使用规范](https://www.nasa.gov/nasa-brand-center/images-and-media/)，不表示 NASA 为本项目或品牌背书。夜景光点、大气光照、轨道与卫星节点为视觉设计；云层使用下述历史合成资源。

云层资源 `static/globe-clouds.jpg` 来自 [NASA《The Blue Marble (2002)》](https://science.nasa.gov/earth/earth-observatory/the-blue-marble-true-color-global-imagery-at-1km-resolution/)。原始云图由两天可见光影像与极地第三天热红外影像合成，署名 NASA Goddard Space Flight Center；Reto Stöckli（云层），Robert Simmon（增强处理）。本机渲染添加光照与透明度，不反映当前天气；来源记录同样保存在 `static/globe-earth-LICENSE.txt`。

此前的 [Natural Earth 陆地轮廓](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/)保留为本地地理资源，相关来源说明见 `static/globe-land-LICENSE.txt`。场景不绘制政治边界，也不用于测绘。
