"""studio.harness - 多 Agent Harness（空间内零模型、零凭据，纯编排与规则）。

分工：state（状态机/轨迹/看板）· roles（5 角色 + 主循环）· critic（规则轨质检）
      guards（真实性校验/假完成拦截）· brain（三档大脑接入）· kit（可执行生产包，P1）

一句话：
    from studio.harness import roles
    st = roles.run_harness("一个机器人学会了说谎", target_seconds=45)
    st.board()          # 制片看板（页面直接渲染）
    st.to_dict()        # 全量（含 trace）
"""
from . import brain, critic, guards, roles, state      # noqa: F401

__all__ = ['state', 'roles', 'critic', 'guards', 'brain']
