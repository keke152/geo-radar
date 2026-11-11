# v1.9.1：地球与六平台卫星轨道

此文保留六平台共同轨道的历史说明。当前版本已更新为 [v1.9.2 独立平台轨道](earth-scene-v192.md)，各平台轨道、图标和反向交互以新版为准。

首页在深空背景上呈现更清晰的大陆纹理、蓝色海洋、云层和大气边缘。豆包、DeepSeek、Kimi、千问、腾讯元宝与知乎直答以六个卫星节点围绕地球运行，轨道具有前后层次，保留原有三角网络的连接感。

## 交互与空间

拖动球体或使用方向键调整视角；暂停和重置按钮用于控制场景。鼠标移入或键盘聚焦卫星节点时暂停轨道运动，便于读取与选择。系统设置“减少动画”时限制自动运动，用户仍可主动查看地球与平台状态。

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

图像来源署名为 NASA Earth Observatory。使用说明参考 [NASA Earth 图像常见问题](https://science.nasa.gov/earth/faq/)与 [NASA 图像和媒体使用规范](https://www.nasa.gov/nasa-brand-center/images-and-media/)，不表示 NASA 为本项目或品牌背书。云层、夜景光点、大气光照、轨道与卫星节点为视觉设计。

此前的 [Natural Earth 陆地轮廓](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/)保留为本地地理资源，相关来源说明见 `static/globe-land-LICENSE.txt`。场景不绘制政治边界，也不用于测绘。
