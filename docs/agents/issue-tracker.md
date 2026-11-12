# Issue tracker（GitHub）

Issue 和规格说明保存在 `MutoMagic/edge-tts-api` 的 GitHub Issues。首次写入前用 `gh repo view --json nameWithOwner` 核对目标。默认目标不同时，用 `--repo MutoMagic/edge-tts-api` 指定仓库。

## Issue 操作

- 发布 Issue 或规格说明时，用 `gh issue create --title "<标题>" --body-file <正文文件>`。
- 读取 Issue 时，用 `gh issue view <编号> --json number,title,body,labels,comments`。
- 列出 Issue 时，用 `gh issue list --state open --json number,title,body,labels,comments`，按需调整 `--state`、`--label` 和 `--limit`。
- 创建子 Issue 用 `gh issue create --parent <父编号> ...`。关联已有 Issue 用 `gh issue edit <父编号> --add-sub-issue <子编号>`。原生子 Issue 功能不可用时，在子 Issue 开头写 `Part of #<父编号>`。
- 用 `gh issue create --blocked-by <编号>,<编号> ...` 为新 Issue 设置依赖，用 `gh issue edit <被阻塞编号> --add-blocked-by <阻塞编号>` 更新已有 Issue。原生依赖不可用时，在正文开头写 `Blocked by: #<编号>, #<编号>`。所有阻塞项关闭后即可开始。
- 用 `gh issue view <编号> --json blockedBy --jq '[.blockedBy.nodes[] | select(.state == "OPEN")] | length'` 统计未关闭的原生阻塞项。依赖记录在正文时，逐一查询所列 Issue 的状态。
- 用 `gh issue comment <编号> --body-file <正文文件>` 添加评论。用 `gh issue edit <编号> --add-label "<标签>"` 或 `--remove-label "<标签>"` 更新标签。
- 关闭 Issue 时，先用评论记录原因，再执行 `gh issue close <编号>`。

## Pull requests as a triage surface

**PRs as a request surface: no.**

启用后，PR 使用相同的分流标签。用 `gh pr view`、`gh pr view --comments` 和 `gh pr diff` 读取，用 `gh pr comment`、`gh pr edit` 和 `gh pr close` 更新。列出外部 PR 时，用 `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open'` 排除作者关联为 `OWNER`、`MEMBER` 或 `COLLABORATOR` 的结果。GitHub 的 Issue 和 PR 共用编号，可先用 `gh pr view <编号>` 判断类型。

## Wayfinder

- 用 `wayfinder:map` 标记地图 Issue，在正文维护 `Notes`、`Decisions-so-far` 和 `Fog`。
- 把任务建为地图的子 Issue，使用对应的 `wayfinder:<type>` 标签。原生子 Issue 功能不可用时，用地图的任务列表链接子 Issue，并在子 Issue 开头写 `Part of #<地图编号>`。
- 按地图顺序选择打开、未指派且没有未关闭阻塞项的子 Issue，用 `gh issue edit <编号> --add-assignee '@me'` 领取。
- 完成后，在子 Issue 评论中记录答案并关闭它，在地图的 `Decisions-so-far` 补充结论和链接。
