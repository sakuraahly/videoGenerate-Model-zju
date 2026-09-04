def send(chat_hist, cid, user_text):
    """重构版 send()：集成 auto-continue + 任务监控。"""
    from runs.agent.session_state import (
        get_stop_event, clear_tasks, add_tasks, increment_turn_id, check_turn_valid
    )
    
    MAX_AUTO_CONTINUE = 2
    ABORT_MARKERS = ('⛔', '不可恢复', '熔断')
    
    user_text = (user_text or '').strip()
    if not _active_turn.acquire(blocking=False):
        yield (fmt_msgs(chat_hist or []),
               BUSY_HTML('上一轮仍在处理中，本次点击已忽略'),
               '上一轮仍在处理中；请等状态变绿或点"⏹ 中止本轮"。', gr.update(), cid,
               chat_hist or [], gr.update())
        return
    try:
        global _stop_requested
        _stop_requested = threading.Event()
        
        if _upload_in_progress:
            yield (fmt_msgs(chat_hist or []),
                   BUSY_HTML('上传尚未完成，请稍候再发送'),
                   '⏳ 素材上传进行中，请等待上传完成后再发送。', gr.update(), cid,
                   chat_hist or [], gr.update())
            return
        
        if not user_text:
            yield (fmt_msgs(chat_hist or []), IDLE_HTML, '请输入内容。', gr.update(), cid,
                   chat_hist or [], gr.update())
            return
        
        if not cid:
            cid = new_chat_id()
        
        msgs = list(chat_hist or [])
        stop_event = get_stop_event(cid)
        stop_event.clear()
        clear_tasks(cid)
        current_turn_id = increment_turn_id(cid)
        
        ev = queue.Queue()
        stop_hb = threading.Event()
        clear_box = gr.update(value='')

        def _heartbeat():
            t0 = time.time()
            while not stop_hb.is_set():
                secs = int(time.time() - t0)
                text = BUSY_HTML(
                    f'处理中 {secs}s · LLM:{llm_state_text()} · '
                    f'引擎: {tail_run_log() or "等待引擎事件"}')
                ev.put({'kind': 'hb', 'text': text})
                stop_hb.wait(HEARTBEAT_SEC)

        threading.Thread(target=_heartbeat, daemon=True).start()
        
        all_pending_tasks = []
        monitor_reported_completion = False
        noop = gr.update()
        first = True
        final_text = ''
        phase = 'ok'
        aborted = False
        
        try:
            for attempt in range(MAX_AUTO_CONTINUE + 1):
                if stop_event.is_set() or _stop_requested.is_set():
                    aborted = True
                    break
                
                if attempt == 0:
                    msgs.append({'role': 'user', 'content': user_text})
                
                shown = fmt_msgs(msgs)
                
                turn_args = (msgs[:-1] if attempt > 0 else msgs[:-1], 
                            user_text if attempt == 0 else None, ev)
                threading.Thread(target=run_turn, args=turn_args, daemon=True).start()
                
                while True:
                    if stop_event.is_set() or _stop_requested.is_set():
                        aborted = True
                        break
                    
                    if not check_turn_valid(cid, current_turn_id):
                        aborted = True
                        break
                    
                    try:
                        item = ev.get(timeout=0.5)
                    except queue.Empty:
                        yield shown, BUSY_HTML('处理中...'), '', noop, cid, msgs, (clear_box if first else noop)
                        first = False
                        continue
                    
                    kind = item.get('kind')
                    if kind in ('hb', 'phase'):
                        status_text = item.get('text', '')
                        yield shown, status_text, '', noop, cid, msgs, (clear_box if first else noop)
                        first = False
                    elif kind == 'done':
                        final_text = item.get('text') or ''
                        phase = 'ok'
                        break
                    elif kind == 'error':
                        phase = 'error'
                        final_text = item.get('text') or '未知错误'
                        break
                
                if aborted or phase == 'error':
                    break
                
                prompt_ids = extract_prompt_ids(final_text)
                if prompt_ids:
                    tasks = [{'prompt_id': pid, 'type': 'single'} for pid in prompt_ids]
                    all_pending_tasks.extend(tasks)
                
                needs_continuation = (
                    final_text and 
                    not any(marker in final_text for marker in ABORT_MARKERS) and
                    not prompt_ids
                )
                
                if not needs_continuation or attempt >= MAX_AUTO_CONTINUE:
                    break
                
                msgs.append({"role": "system", "content": '[系统自动续接] 请继续完成当前任务。'})
                user_text = None
                yield (shown, BUSY_HTML('自动续接中...'), ' 自动续接中...', noop, cid, msgs, noop)
        
        finally:
            stop_hb.set()
        
        add_tasks(cid, all_pending_tasks)
        
        if all_pending_tasks and check_turn_valid(cid, current_turn_id):
            try:
                from runs.agent.task_watch import _monitor_worker
                monitor_queue = queue.Queue(maxsize=10)
                monitor_thread = threading.Thread(
                    target=_monitor_worker, 
                    args=(cid, current_turn_id, monitor_queue, stop_event),
                    daemon=True
                )
                monitor_thread.start()
                
                while True:
                    try:
                        msg = monitor_queue.get(timeout=0.5)
                    except queue.Empty:
                        if not monitor_thread.is_alive():
                            break
                        if not check_turn_valid(cid, current_turn_id) or stop_event.is_set():
                            break
                        continue
                    
                    if msg['type'] == 'update':
                        yield (gr.update(), msg['status_html'], msg['note_md'], noop, cid, msgs, noop)
                    elif msg['type'] == 'done':
                        monitor_reported_completion = True
                        if msg['status_html']:
                            yield (gr.update(), msg['status_html'], msg['note_md'], noop, cid, msgs, noop)
                        break
            except Exception:
                pass
        
        if aborted or _stop_requested.is_set():
            final_status = ABORT_HTML
            note = '已中止本轮。'
            msgs.append({'role': 'assistant', 'content': '[已中止]'})
        elif phase == 'error':
            final_status = ERROR_HTML
            msg = f'[执行出错] {final_text}'
            msgs.append({'role': 'assistant', 'content': msg})
            note = '上一轮执行出错'
        elif final_text:
            final_status = IDLE_HTML
            msgs.append({'role': 'assistant', 'content': final_text})
            note = '✅ 本轮完成'
        else:
            final_status = IDLE_HTML
            msgs.append({'role': 'assistant', 'content': '(模型未返回内容)'})
            note = '模型未返回内容'
        
        save_chat(cid, msgs)
        
        if check_turn_valid(cid, current_turn_id):
            if stop_event.is_set() or _stop_requested.is_set():
                yield (msgs, ABORT_HTML, ' 已中止', noop, cid, msgs, [])
            elif monitor_reported_completion:
                yield (msgs, noop, noop, noop, cid, msgs, [])
            else:
                yield (msgs, final_status, note, gr.update(choices=_choices()), cid, msgs, clear_box)
    finally:
        _active_turn.release()
