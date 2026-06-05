const e={overview:"概览",workspace:"工作区",graph:"图谱",memories:"记忆",calendar:"日历",user:"用户",peers:"同伴",changes:"变更",insights:"洞察",settings:"设置",brand_sub:"记忆智能",agents_clones:"智能体与克隆",all_namespaces:"全部命名空间",graph_legend:"图谱图例",shared_entity:"共享实体",superseded:"已替换（历史）",search_ph:"在记忆中检索……（语义 + 词法 · 已排序）",memories_word:"条记忆",all_word:"全部",add_memory:"添加到记忆",durable_memory:"持久记忆",user_observation:"用户观察",memory_ph:"一条需要记住的持久事实……",observation_ph:"关于该用户的某个真实信息……",save:"保存",saving:"保存中……",cmd_save:"⌘↵ 保存",recall:"回忆",no_match:"没有匹配的记忆。",recent_activity:"近期活动",insight:"洞察",whats_notable:"值得关注的内容",knowledge_communities:"知识社群",total:"总计",nothing_here:"这里还没有内容。",no_memories_yet:"还没有记忆。",click_to_open:"点击打开",relations:"关系",connected:"已连接",pick_day:"选择某一天",memories_on:"记忆日期",no_memories_day:"这一天没有记忆。",select_day:"在日历上选择某一天以查看当天的记忆。",jump_today:"跳到今天",busier:"颜色越深 = 越繁忙",memories_this_month:"本月记忆",user_model:"用户模型",no_user_model:"还没有用户模型。用 observe_user(…) 来填充它。",pick_peer:"选择一组同伴关系",believes_about:"{a} 对 {b} 的看法",no_peer_obs:"还没有同伴观察。",contradictions:"矛盾 · 随时间发生的变化",no_contradictions:"没有矛盾——目前还没有任何取值随时间发生变化。",changelog:"变更日志 · 所学到的内容",nothing_window:"此时间段内没有学到内容。",contras_desc:"当某条事实的取值发生变化时，旧值会被作废，而非删除。任意时间点的历史仍可查询。",current_now:"当前",since_word:"自",until_word:"至",not_enough_reflect:"记忆还不足以进行反思。",no_graph:"还没有图谱。",appearance:"外观",theme:"主题",dark:"深色",light:"浅色",auto:"自动",language:"语言",behavior:"行为",animations:"图谱动画",animations_desc:"知识图谱中的实时物理效果",done:"完成",open_settings:"设置",menu:"菜单",sessions:"会话",no_sessions:"还没有会话。",pick_session:"选择一个会话",week:"周",month:"月",data:"数据",export_json:"导出记忆（JSON）",aliases:"别名",type_word:"类型",colored_by_community:"按社群着色",dreams:"梦境",dream_journal:"梦境日志",dream_cycle:"周期",no_dreams:"还没有梦境周期。运行 mind.dream() 开始。",consolidated:"已巩固",distilled:"已提炼",reinforced:"已强化",forgotten:"已遗忘",derived:"已推导",inferred:"已推断",graph_edges:"图谱边",user_synthesized:"用户模型已更新",rename_session:"重命名会话",session_name:"会话名称",rename:"重命名",importing:"导入中……",import_claude:"从 Claude Code 导入",contested_beliefs:"有争议的信念",contested_desc:"发生变化时，双方都具有高置信度。",surprise_score:"惊讶度",no_contested:"没有有争议的信念——未发现高置信度的矛盾。",danger_zone:"危险区域",clear_layer:"按层清除",clear_stale:"清除过期项",clear_all_ns:"重置命名空间",confirm_clear:"输入 CLEAR 以确认",cleared:"已清除",clearing:"清除中……",forget_curve:"遗忘曲线",retention:"留存率",projected:"预计 7 天",days_since:"距上次回忆天数",graph_communities:"社群",graph_history:"历史",graph_time:"时间",graph_shake:"抖动",graph_fit:"适配",graph_areas:"生活领域",graph_colored_by_area:"按生活领域着色",graph_color_by:"着色方式",graph_color_namespace:"Namespace",graph_color_community:"社群",graph_color_area:"生活领域",graph_color_centrality:"中心度",graph_layers:"图层",glayer_relation:"关系",glayer_comention:"共同提及",glayer_semantic:"语义",graph_filters:"筛选",graph_min_conf:"最低置信度",graph_search:"查找实体……",graph_predicates:"关系类型",graph_reset:"重置",colored_by_centrality:"按中心度着色（大小 = 重要性）",pclass_social:"社交",pclass_has:"拥有",pclass_causal:"因果",pclass_locative:"位置",pclass_temporal:"时间",pclass_is_a:"属于",pclass_other:"其他",cent_low:"低",cent_hub:"枢纽",pred_works_at:"工作于",pred_reports_to:"汇报给",pred_part_of:"隶属于",pred_owns:"拥有",pred_leads:"领导",pred_founded:"创立",pred_scheduled_for:"安排于",pred_studies:"研究",pred_manages:"管理",pred_knows:"认识",pred_based_in:"驻于",pred_located_in:"位于",pred_lives_in:"居住于",pred_invested_in:"投资于",pred_married_to:"结婚于",pred_depends_on:"依赖于",pred_blocks:"阻塞",pred_uses:"使用",pred_created:"创建",pred_member_of:"是其成员",pred_works_with:"合作于",pred_focus:"专注于",pred_has:"拥有",graph_local:"局部",graph_depth:"深度",graph_focus_here:"聚焦于此",graph_exit_local:"退出局部视图",graph_path:"路径",graph_path_from:"起始实体",graph_path_to:"目标实体",graph_path_find:"追踪",graph_no_path:"两者之间没有路径。",graph_path_hint:"A 与 B 有何关联？",glayer_suggested:"建议",legend_bridge:"桥梁（关键支撑）",legend_suggested:"建议链接",node_unlinked:"被一同提及，但未链接",graph_highlight:"高亮匹配项",tip_search:"搜索并跳转到某个实体",tip_colour:"按命名空间、社群、生活领域或中心度为节点着色",tip_comention:"被一同提及的实体之间涌现的链接",tip_semantic:"记忆相似的实体之间的链接（需要嵌入器）",tip_suggested:"预测存在但缺失、你可能想添加的链接",tip_filters:"最低置信度、关系类型及按查询高亮",tip_path:"追踪某个实体如何与另一个实体关联",tip_history:"包含已归档 / 已替换的事实",tip_time:"拖动时间轴以查看过去某日期的图谱",tip_shake:"重新激活布局",tip_fit:"将整个图谱适配到视图中",graph_entities:"实体",graph_as_of:"截至",graph_empty:"此视图的图谱为空。",graph_tip:"提示：点击节点查看其记忆 · 拖动可移动 · 滚动可缩放 · ⬡ 按社群着色。",timeline:"时间轴",loading:"加载中……",no_entity_memories:"还没有记忆提及此实体。",portable_bundle:"可移植包",dream_noop:"空操作周期（离线或无内容可处理）",no_claude_sessions:"未发现新的 Claude Code 会话。",layer_episodic:"情景",layer_semantic:"语义",layer_graph:"图谱",layer_user:"用户",weekdays:"日,一,二,三,四,五,六",months:"一月,二月,三月,四月,五月,六月,七月,八月,九月,十月,十一月,十二月",forget_entity:"擦除实体",forget_entity_confirm:"擦除所有提及该实体的记忆",forget_entity_btn:"擦除（GDPR）",erasing:"擦除中……",erased:"已擦除",ask_about_user_ph:"询问关于此用户的问题……",ask_btn:"提问",asking:"提问中……",stale_beliefs:"待重新核实的信念",stale_desc:"陈旧、从未被回忆、置信度低。",no_stale:"没有过期信念——所有内容近期都被回忆过。",age_days:"天前",confidence:"置信度",import_bundle:"导入包",importing_bundle:"导入中……",import_success:"已导入",import_error:"导入失败",prov_distilled:"提炼/推断而来——其来源未被链接。",prov_direct:"直接捕获（无上游来源）。",prov_supersedes:"替换了一条先前的记忆。",workspace_dna_title:"工作区 · 项目 DNA",workspace_dna_desc:"读取任意文件夹的结构，让系统理解它的运作方式。",workspace_path_ph:"/path/to/a/repo （留空 = 服务器的工作目录）",scan_word:"扫描",scanning_word:"扫描中……",ws_languages:"语言",ws_files:"个文件",ws_no_code:"未检测到代码。",ws_frameworks:"框架",ws_none:"未检测到任何内容。",ws_key_files:"关键文件",properties:"属性",why_believe:"我为何相信这一点",conn_sub:"自动发现——无手动链接",back:"返回",grp_person:"人物",grp_projects:"项目",grp_organization:"组织",grp_business:"商业",maslow_self_actualization:"自我实现",maslow_esteem:"尊重",maslow_belonging:"爱与归属",maslow_safety:"安全",maslow_physiological:"生理",tag_agent:"智能体",tag_entity:"实体",context_included_short:"位于",conn_mentions:"提及",conn_relations:"关系",conn_backlinks:"链接至此",conn_related:"相关",conn_none:"还未发现任何连接。",prop_agent:"智能体",prop_session:"会话",prop_date:"日期",prop_source:"来源",prop_importance:"重要性",prop_tags:"标签",prop_relation:"关系",prop_category:"类别",prop_id:"ID",captured_via:"捕获方式",delete_word:"删除",recalled_word:"已回忆",cluster_word:"聚类",no_data_yet:"还没有数据。",from_word:"来自",export_session:"导出会话",no_peer_card:"还没有卡片。",select_peer_rel:"选择一组关系以查看其定向画像。",no_memories:"无记忆",entries_word:"条目",clear_error:"清除时出错。",stale_60d:"已过期（>60 天）",namespace_word:"Namespace",expiring_word:"即将过期",avg_word:"平均",ops_word:"操作",total_ops:"总操作数",no_beliefs_at_risk:"未来 7 天内没有面临风险的信念。",participants:"参与者",portable_bundle_tip:"可在应用/厂商之间迁移的可移植记忆",demo_empty:"此仪表板为空。加载一个虚构的演示数据集来探索每项功能。",demo_load:"加载演示",demo_loading:"加载中……",demo_loaded:"你正在查看虚构的演示数据。准备使用自己的数据时请将其清除。",demo_clear:"清除演示",demo_keep:"保留",learning:"学习中……",learned:"已学习",learn_updating:"正在更新记忆 {i}/{n}……",learn_done:"已捕获 {n} 条事实",learn_known:"已知",learn_known_desc:"这已存在于记忆中——未存储重复项；现有记忆保持不变。",learn_extracted:"已提取 {n} 条事实",learn_resolved:"已与记忆比对核查",learn_stored:"已存储并建立索引",learn_linked:"已链接 {n} 条关系",learn_user:"用户模型已更新",op_new:"新增",op_updated:"已更新",op_was:"原为",cat_explore:"探索",cat_memory:"记忆",cat_intelligence:"智能",cat_system:"系统",integrations:"集成",integrations_sub:"驱动此实例的技术栈——以及你可以接入的内容。",intg_active:"当前技术栈",intg_llm:"LLM",intg_embedder:"嵌入器",intg_store:"存储",intg_reranker:"重排器",intg_none:"无",intg_offline:"离线",intg_redundant:"镜像分布于",intg_dims:"维",intg_llms:"语言模型",intg_embedders:"嵌入器",intg_rerankers:"重排器",intg_stores:"存储与后端",st_active:"启用中",st_ready:"就绪",st_setkey:"设置 {env}",st_install:"安装",st_available:"可用",settings_general:"通用",spotlight_open:"搜索一切……",spotlight_ph:"搜索记忆、实体、智能体、视图……",spotlight_hint:"跨记忆、实体、智能体和视图搜索",spotlight_empty:"无结果",grp_views:"视图",grp_agents:"智能体",grp_memories:"记忆",grp_entities:"实体",profile:"画像",profile_sub:"每条事实按生活与工作维度分类，并映射到 Maslow。",profile_empty:"还没有已分类的事实。",profile_empty_hint:"分类需要 LLM（一个 API 密钥，或本地 Claude CLI）。添加一条记忆即可看到它被自动整理。",profile_maslow:"Maslow 需求层次",profile_cards:"卡片视图",profile_map:"知识地图",grp_categories:"类别",dim_filter_all:"所有维度",help_profile:`画像
你存储的每条事实，按生活与工作维度分类，并映射到 Maslow 的需求层次。
• 分组卡片（个人 / 项目 / 组织 / 商业与财务）——各类别下有多少条事实。
• 每张维度卡片显示其 Maslow 层级（针对个人）及其下的开放类别和计数。
• 点击某个类别可跳转到其背后的记忆。
• 分类在捕获时发生，并需要 LLM（一个 API 密钥，或本地 Claude CLI）。`,help_word:"帮助",help_overview:`概览
你的记忆库与近期活动的快照。
• 总计——此命名空间下所有层级中存储的全部记忆合计数量。
• 层级统计——每个记忆层级各有一张计数卡片，以颜色区分以显示层级分布。
• 洞察——从你的记忆中自动生成的摘要洞察；有可用内容时显示。
• 近期活动——库中最新添加的 8 条记忆列表，以单独卡片形式展示。`,help_analytics:`分析
一目了然地查看你的记忆系统的规模、结构与健康状况。
• 顶部的统计卡片显示总量：你拥有多少条记忆、智能体、实体、关系、会话和检测到的矛盾，以及平均响应延迟和错误率。
• 四张图表分别按时间（最近 30 天）、存储层级（情景/语义/图谱/用户）、数据来源和顶级智能体展示记忆构成。
• 记忆湖表格列出每个命名空间（智能体、用户或领域），含实体、事实、关系数量、活动趋势及上次更新时间。
• 记忆湖中的每一行都有一个彩色圆点和类型徽章（USER/ORG/DOMAIN/AGENT），帮助你一眼归类和识别命名空间。
• 底部的治理徽章确认每条记忆都被追踪溯源、正确标注来源、版本化，并可应请求擦除。`,help_context:`上下文块
此页面根据你的查询和令牌预算，将记忆组装成可直接用于提示的块。
• 查询输入：输入你需要智能体记住的内容（例如「发布时间表、优先级、相关人员」）以跨记忆层级搜索。
• 预算选择器：选择组装后的块可使用多少令牌（600、1200、2000 或 4000）——LLM 的上下文窗口有限，因此预算限定了能放入提示的令牌数量，仅注入在此限制内排名最高的记忆。
• 令牌进度条：显示你组装的块相对于预算使用了多少令牌（例如「245 / 1200 令牌」），以及所选候选项的百分比和数量。
• 排序候选项（左）：列出所有被纳入考虑的记忆，按相关性得分排序。带绿色对勾和实线边框的记忆被纳入最终块；变淡的则未能放入令牌预算。
• 组装块（右）：最终的 markdown 格式块，可直接注入你的提示，分为多个区块并附每个区块的令牌估算，还有一个复制按钮可将其发送到剪贴板。`,help_graph:`图谱
你的知识化作一张活的地图——实体及它们随时间如何相互连接。
• 边的语法——每条关系按其类型着色（社交、拥有、因果、位置、时间），并用箭头表示方向；越粗 = 置信度越高。共同提及为虚线，建议链接为金色点线，已替换的事实变灰。
• 节点大小——节点越大越居中（PageRank 重要性），因此枢纽更突出；桥梁带有虚线环。
• 颜色——选择节点的着色方式：Namespace、社群、生活领域或中心度（冷→热）。
• 连接层——切换共同提及（被一同提及的实体）、语义（记忆相似）和建议（预测存在但缺失的链接）。
• 路径——追踪「A 与 B 有何关联？」，连接链会在画布上点亮。
• 查找与聚焦——搜索以跳转到某个节点；打开一个节点并「聚焦于此」即可只查看其局部图谱（带深度滑块）。将鼠标悬停在任意节点上可预览其事实。
• 筛选——最低置信度滑块、按关系类型切换，以及按查询高亮。
• 历史与时间——包含已归档的事实，或拖动时间轴以查看任意过去日期的图谱。
• 图例与详情——打开图例查看颜色 + 边的图例；点击任意节点查看其记忆、连接和未链接的提及。`,help_memories:`记忆
查看并管理智能体存储的所有记忆。
• 层级筛选——点击顶部的标签按记忆类型筛选（全部、情景、语义、程序性）以查看不同类别。
• 记忆卡片——每张卡片显示一条存储的记忆及其内容和元数据；点击删除按钮可将其永久移除。
• 打开时高亮——当你导航到某条特定记忆时，它会短暂高亮，方便你在列表中找到它。
• 空状态——如果没有记忆匹配你的筛选，你会看到列表为空的提示。`,help_calendar:`日历
以交互式热力图按天查看你的记忆活动。
• 热力图——每个日期格显示当天存储的记忆数量；蓝色越深 = 越活跃。
• 今日标记——金色边框高亮今天的日期，便于快速参考。
• 已选日期——点击任意一天，用蓝色环高亮它并在右侧查看当天的记忆。
• 模式切换——在月视图（一次显示整月）和周视图（7 天快照）之间切换。
• 导航——使用箭头按钮在月份或周之间前后移动。
• 当日面板——右侧面板将所选日期保存的所有记忆以单独卡片形式展示。
• 跳到今天——点击此按钮即可立即返回当前日期。`,help_sessions:`会话
查看并管理你的 AI 智能体对话会话及其存储的记忆。
• 会话列表（左）：显示所有会话的名称、记忆数量、上次活动日期、命名空间和来源。
• 选择会话：点击列表中的任意会话即可在右侧查看其记忆和详情。
• 重命名会话：点击所选会话名称旁的铅笔图标即可编辑。
• 会话详情（右）：显示会话记录头部（状态、参与者、指标、链接）以及以卡片形式呈现的所有相关记忆。
• 导出：点击下载图标可将所选会话及其记忆导出为 JSON。
• 导入 Claude：点击「↓ Claude」按钮即可从 Claude 导入对话会话。`,help_user:`用户模型
查看并查询 AI 智能体为特定用户学到的画像。
• 提问区——输入关于该用户的问题，从存储的画像中获取洞察。
• 提问按钮——提交你的问题，根据智能体的知识获得答案。
• 答案显示——显示对你问题的回应，提交后出现在输入框下方。
• 画像视图——以格式化文本块显示完整的用户画像数据；若尚无画像，则显示提示信息。`,help_peers:`同伴
探索某个智能体或实体对另一个的看法或了解。
• 同伴关系列表：显示所有定向对（观察者 → 被观察者），含观察数量及其命名空间。
• 观察者与被观察者：左侧名称是做出观察的一方，箭头指向被观察的一方。
• 计数徽章：每对右侧显示的数字表示该关系存在多少条观察。
• 信念卡片：选择一对以查看某个同伴记录的关于另一个的具体信念或事实，以要点形式展示。
• 命名空间标签：一个小标签，显示该同伴关系所属的命名空间，帮助在不同情境中组织关系。`,help_observations:`观察
此页面显示在你的命名空间中发现的关于实体的模式和连接。
• 反复出现的配对——经常一同出现的实体配对，以合并图标显示。
• 中心实体——连接到许多其他实体的关键实体（枢纽），以圆圈图标显示。
• 实体徽章——彩色标签，显示每条观察中涉及的实体。
• 计数徽章——显示此观察拥有多少条关系（对于枢纽）或共享情境。
• 描述文本——对该模式或连接的简要说明。
• 共享情境——标签，显示这些实体是在哪些情境或来源中被连接起来的。`,help_changes:`变更
随时间查看记忆更新并检测矛盾。
• 矛盾：显示同一主体存在相互冲突取值的事实。绿色徽章显示当前事实，灰色删除线显示过去已替换的取值及其日期。
• 变更日志：按倒序时间列出所有记忆变更。显示变更日期、它影响了哪个层级、改变了什么及其命名空间。
• 时间范围按钮（7 天、30 天、90 天）：筛选变更日志，仅显示最近 7、30 或 90 天的变更。仅影响变更日志，不影响矛盾。`,help_insights:`洞察
查看记忆中值得关注内容的摘要，并审阅可能已过时的信念。
• 过期信念：显示正在老化的已存储信念（含天数和置信度分数）。点击展开以审阅可能需要更新的内容。
• 值得关注的内容：从你的记忆中提取的模式和重要信息的自动生成摘要。
• 知识社群：显示相关实体及其连接的聚类，按相关性和规模组织。`,help_workspace:`工作区
分析任意项目文件夹的结构和构成。
• 路径输入——输入或粘贴文件夹路径，然后按回车或点击扫描以分析项目。
• 语言——显示项目中使用了哪些编程语言，并用条形图标示各自有多少文件使用。
• 框架——显示在项目中检测到的框架和依赖项。
• 关键文件——列出定义项目结构的重要项目文件（如配置文件、入口点或清单文件）。
• 文件总数——数字徽章显示在所有语言中共扫描了多少文件。`,help_dreams:`梦境
追踪记忆巩固周期，并识别需要关注的信念。
• 摘要卡片：查看已运行的梦境周期总数、提炼成记忆的信念、被遗忘的信念，以及执行的总操作数。
• 遗忘曲线：查看面临淡化风险的记忆，含留存百分比和 7 天强度预测，帮助你强化正在减弱的信念。
• 有争议的信念：发现已被更新的冲突信念，将当前信念与已替换的信念并列显示，并附置信度分数。
• 惊讶事件：回顾系统遇到意外信息的时刻，惊讶度分数表明新数据与既有知识的矛盾程度。
• 梦境周期：浏览单次梦境巩固运行，每次显示提炼、强化、遗忘、推导、推断的信念数量及新增的图谱边。`,help_settings:`设置
自定义你的记忆仪表板的外观和行为，管理数据的导入导出，并与外部工具集成。
• 主题——在深色模式、浅色模式或自动（跟随系统偏好）之间选择。
• 语言——为仪表板界面选择你偏好的语言。
• 动画——开启或关闭视觉动画，以获得更流畅的体验。
• 集成——连接外部应用和服务以存储和检索记忆。
• 数据——将记忆导出为 JSON 或可移植包，或导入此前保存的数据。
• 危险区域——永久删除特定层级的记忆，或移除过期条目（超过 60 天）。`,analytics:"分析",analytics_sub:"使用情况、活动与可靠性。",memories_over_time:"已添加记忆",last_30_days:"最近 30 天",all_time:"全部时间",open_in_graph:"在图谱中打开",open_in_memories:"在记忆中打开",last_n_days:"最近 {n} 天",by_layer:"按层级",by_source:"按来源",by_agent:"按智能体",avg_latency:"平均延迟",requests_word:"请求",error_rate:"错误率",memory_lake:"记忆湖",lake_subject:"主体",lake_entities:"实体",lake_facts:"事实",lake_activity:"活动",lake_updated:"已更新",lake_type:"类型",gov_provenance:"溯源",gov_erase:"可 GDPR 擦除",gov_versioned:"已版本化",gov_sourced:"已标注来源",gov_note:"在可用时标注来源并追踪溯源；更新已版本化；每一行均可应请求擦除。",context:"上下文",context_block:"上下文块",context_block_sub:"智能组装——按令牌预算适配的排序候选项。",context_query_ph:"智能体需要知道什么？",token_budget:"令牌预算",tokens_word:"令牌",utilized:"已使用",candidates_selected:"已选",ranked_candidates:"排序候选项",assembled_block:"组装块",copy:"复制",copied:"已复制",context_empty:"输入查询以组装上下文块。",context_foot:"仅注入排名最高且符合预算的记忆——绝不浪费。",observations:"观察",observations_sub:"跨众多事实的模式——而非存在于任何单条事实之中。",observations_empty:"图谱还不足以检测模式。",recurring_pairs:"反复一同出现",central_entities:"中心实体",relations_word:"关系",shared_word:"共享",observations_foot:"从时间图谱中按结构检测——连通性与共现，随记忆增长重新计算。"};export{e as default};
