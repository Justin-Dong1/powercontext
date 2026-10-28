# 验证样例

## 样例 A：第一次进入

- 初始状态：使用 `scripts/powercontext_demo.py` 创建的新 Scope，尚无回声迷宫记忆。
- 输入：`player_name=阿澈`，`choice=红门`。
- 预期：输出显示“已召回旧回声：0 条”，进入“倒悬钟楼”；PowerContext 写入状态为 `200`。

## 样例 B：同一选择触发回头客彩蛋

- 初始状态：沿用样例 A 的同一个 `scope_id`。
- 输入：`player_name=阿澈`，`choice=红门`。
- 预期：至少召回 1 条旧回声，剧情包含“上次已经选过这里”和“回头客才能看到的暗道”；本回合再次写入 PowerContext。

## 样例 C：改变选择

- 初始状态：沿用样例 A 的同一个 `scope_id`。
- 输入：`player_name=阿澈`，`choice=蓝门`。
- 预期：能够召回旧回声，但进入“潮汐图书馆”，剧情说明“这次选择不同”。

## 恢复初始状态

创建一个新的 Scope，或换用不同的 `scope_id`。不要删除其他参赛者或用户的 Scope/Memory。
