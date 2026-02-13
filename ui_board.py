import streamlit as st
import pandas as pd
import datetime
import base64
import calendar
from firebase_admin import firestore

def render_notice_board(db):
    st.title("📢 공지사항")
    
    # [수정] 카드 레이아웃 및 링크 스타일 추가
    st.markdown("""
    <style>
        .notice-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: bold; margin-right: 5px; }
        .badge-important { background-color: #ffebee; color: #c62828; }
        .badge-normal { background-color: #e3f2fd; color: #1565c0; }
    </style>
    """, unsafe_allow_html=True)

    # 현재 사용자 정보
    current_user_name = st.session_state.get("user_name", "Unknown")
    current_user_id = st.session_state.get("user_id", "")
    current_user_dept = st.session_state.get("department", "")
    current_role = st.session_state.get("role", "user")

    # [NEW] 만료된 게시물 자동 삭제 (현재 시간 기준)
    try:
        now = datetime.datetime.now()
        # expiration_date 필드가 있고, 현재 시간보다 과거인 문서 조회 및 삭제
        expired_docs = db.collection("posts").where("expiration_date", "<", now).stream()
        for doc in expired_docs:
            db.collection("posts").document(doc.id).delete()
    except Exception:
        pass # 인덱스 오류 등 예외 발생 시 무시 (최초 실행 시 발생 가능)

    # [NEW] 작성 중 상태 확인 (리런 시 닫힘 방지)
    is_writing = (
        st.session_state.get("np_title") or 
        st.session_state.get("np_content") or 
        st.session_state.get("np_file")
    )

    # [NEW] 공지사항 작성 폼 열림/닫힘 상태 관리
    if "notice_expander_state" not in st.session_state:
        st.session_state["notice_expander_state"] = False
    
    # 작성 중이면 열어두기 (등록 직후에는 is_writing이 False가 됨)
    if is_writing:
        st.session_state["notice_expander_state"] = True

    # [NEW] 화면 모드 초기화
    if "notice_view_mode" not in st.session_state:
        st.session_state["notice_view_mode"] = "list"
    if "notice_list_key" not in st.session_state:
        st.session_state["notice_list_key"] = 0
    # [수정] URL 쿼리 파라미터를 사용하여 뷰 상태 관리 (브라우저 뒤로가기 지원)
    if 'notice_id' in st.query_params:
        st.session_state["notice_view_mode"] = 'detail'
        st.session_state["selected_post_id"] = st.query_params['notice_id']
    elif st.session_state["notice_view_mode"] == 'detail':
        st.session_state["notice_view_mode"] = 'list'
        st.session_state["selected_post_id"] = None
        # [FIX] 뒤로가기 시 목록 선택 상태 초기화를 위해 키 증가
        st.session_state["notice_list_key"] += 1

    view_mode = st.session_state["notice_view_mode"]
    selected_id = st.session_state.get("selected_post_id")

    # 공지사항 작성 (접기/펼치기)
    if view_mode == "list":
        # [수정] expanded 상태를 세션 변수로 제어
        with st.expander("✏️ 새 공지사항 작성", expanded=st.session_state["notice_expander_state"]):
            # [수정] st.form 제거하여 동적 UI(기간 설정) 즉시 반응하도록 변경
            title = st.text_input("제목", key="np_title")
            content = st.text_area("내용", height=100, key="np_content")
            
            c1, c2 = st.columns(2)
            
            # [NEW] 공지 대상 선택 (통합형)
            # 사용자 목록 가져오기
            users_ref = db.collection("users").stream()
            users_opts = [f"{u.to_dict().get('username')} ({u.to_dict().get('name')})" for u in users_ref]
            
            # '전체 공지'를 옵션의 첫 번째에 추가
            target_options = ["전체 공지"] + users_opts
            
            # 멀티 셀렉트 (기본값: 전체 공지)
            selected_targets = c1.multiselect("공지 대상 선택", target_options, default=["전체 공지"], key="np_targets")
                
            # [NEW] 게시 기간 설정
            c_t1, c_t2 = st.columns(2)
            post_term = c_t1.radio("게시 기간", ["영구 게시", "기간 설정"], horizontal=True, key="np_term")
            expiration_date = None
            if post_term == "기간 설정":
                exp_date = c_t2.date_input("게시 종료일", datetime.date.today() + datetime.timedelta(days=7), key="np_exp_date")
                expiration_date = datetime.datetime.combine(exp_date, datetime.time.max)

            # [NEW] 첨부파일 업로드
            uploaded_file = st.file_uploader("첨부파일 (이미지/문서)", type=['png', 'jpg', 'jpeg', 'pdf', 'xlsx', 'txt'], key="np_file")
            
            is_important = st.checkbox("중요(상단 고정)", key="np_important")
            
            if st.button("등록", type="primary"):
                if title and content:
                    if not selected_targets:
                        st.error("공지 대상을 선택해주세요.")
                        st.stop()

                    # 대상 처리 로직
                    if "전체 공지" in selected_targets:
                        target_type = "전체공지"
                        target_value = []
                    else:
                        target_type = "대상선택"
                        target_value = selected_targets

                    # 파일 처리 (Base64 인코딩하여 Firestore에 저장 - 용량 제한 주의)
                    file_data = None
                    file_name = None
                    if uploaded_file:
                        if uploaded_file.size > 1024 * 1024: # 1MB 제한
                            st.error("첨부파일은 1MB 이하여야 합니다.")
                            st.stop()
                        file_bytes = uploaded_file.read()
                        file_data = base64.b64encode(file_bytes).decode('utf-8')
                        file_name = uploaded_file.name

                    doc_data = {
                        "title": title,
                        "content": content,
                        "author": current_user_name,
                        "author_id": current_user_id,
                        "created_at": datetime.datetime.now(),
                        "is_important": is_important,
                        "target_type": target_type,
                        "target_value": target_value, # list or string
                        "expiration_date": expiration_date,
                        "file_name": file_name,
                        "file_data": file_data,
                        "views": 0
                    }
                    db.collection("posts").add(doc_data)
                    st.success("등록되었습니다.")
                    
                    # 입력 필드 초기화 (세션 상태 삭제)
                    keys_to_clear = ["np_title", "np_content", "np_targets", "np_term", "np_exp_date", "np_file", "np_important"]
                    for k in keys_to_clear:
                        if k in st.session_state:
                            del st.session_state[k]
                    
                    # [NEW] 등록 후 폼 닫기
                    st.session_state["notice_expander_state"] = False
                    st.rerun()
                else:
                    st.warning("제목과 내용을 입력하세요.")

        st.divider()

    # [NEW] 검색 필터 세션 초기화
    if "n_search_author" not in st.session_state: st.session_state["n_search_author"] = ""
    if "n_search_keyword" not in st.session_state: st.session_state["n_search_keyword"] = ""
    if "notice_page" not in st.session_state: st.session_state["notice_page"] = 1

    # [NEW] 검색 UI
    with st.expander("🔍 공지사항 검색", expanded=True):
        c1, c2, c3, c4 = st.columns([1, 1, 0.3, 0.3])
        s_author = c1.text_input("작성자", value=st.session_state["n_search_author"])
        s_keyword = c2.text_input("제목+내용", value=st.session_state["n_search_keyword"])
        
        if c3.button("검색", type="primary", use_container_width=True, help="조건에 맞는 공지사항을 검색합니다."):
            st.session_state["n_search_author"] = s_author
            st.session_state["n_search_keyword"] = s_keyword
            st.session_state["notice_page"] = 1 # 검색 시 1페이지로 초기화
            st.session_state["notice_list_key"] += 1
            st.rerun()
            
        if c4.button("전체조회", use_container_width=True, help="검색 조건을 초기화하고 전체 목록을 조회합니다."):
            st.session_state["n_search_author"] = ""
            st.session_state["n_search_keyword"] = ""
            st.session_state["notice_page"] = 1
            st.session_state["notice_list_key"] += 1
            st.session_state["notice_view_mode"] = "list"
            st.session_state["selected_post_id"] = None
            st.query_params.clear()
            st.rerun()

    # 공지사항 목록 조회 (검색을 위해 전체 조회 후 필터링)
    posts_ref = db.collection("posts").order_by("created_at", direction=firestore.Query.DESCENDING)
    all_docs = list(posts_ref.stream())
    
    if all_docs:
        visible_posts = []
        
        # 검색 조건 준비
        f_author = st.session_state["n_search_author"]
        f_keyword = st.session_state["n_search_keyword"]
        
        for doc in all_docs:
            p_data = doc.to_dict()
            p_data['id'] = doc.id
            
            # [NEW] 권한 체크: 내가 볼 수 있는 글인가?
            # 1. 전체공지
            # 2. 내가 작성자
            # 3. 관리자
            # 4. 나에게 온 공지 (대상선택)
            
            t_type = p_data.get('target_type', '전체공지')
            t_val = p_data.get('target_value')
            author_id = p_data.get('author_id')
            
            is_visible = False
            if t_type == "전체공지":
                is_visible = True
            elif current_role == "admin" or author_id == current_user_id:
                is_visible = True
            elif t_type == "대상선택" and isinstance(t_val, list):
                # "아이디 (이름)" 형식에서 아이디가 포함되어 있는지 확인
                for target in t_val:
                    if target.startswith(f"{current_user_id} ("):
                        is_visible = True
                        break
            
            if not is_visible: continue
            
            # [NEW] 검색 필터 적용
            
            # 2. 작성자
            if f_author and f_author not in p_data.get('author', ''): continue
            
            # 3. 키워드 (제목+내용)
            if f_keyword:
                txt = f"{p_data.get('title', '')} {p_data.get('content', '')}"
                if f_keyword not in txt: continue

            visible_posts.append(p_data)
        
        # 필독/일반 정렬 (중요한 것 우선, 그 다음 최신순)
        visible_posts.sort(key=lambda x: (x.get('is_important', False), x.get('created_at', datetime.datetime.min)), reverse=True)
        
        # [NEW] 페이징 처리
        items_per_page = 10
        total_items = len(visible_posts)
        total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
        
        if st.session_state["notice_page"] > total_pages: st.session_state["notice_page"] = total_pages
        if st.session_state["notice_page"] < 1: st.session_state["notice_page"] = 1
        
        curr_page = st.session_state["notice_page"]
        start_idx = (curr_page - 1) * items_per_page
        end_idx = start_idx + items_per_page
        
        page_posts = visible_posts[start_idx:end_idx]

        # 목록 렌더링 함수 (재사용)
        def render_notice_list(posts, current_selected_id=None):
            df_rows = []
            for p in posts:
                is_imp = p.get('is_important', False)
                title_display = p['title']
                if p.get('file_name'):
                    title_display = f"{title_display} [💾첨부파일]"
                
                created_at = p.get('created_at')
                date_str = created_at.strftime("%Y-%m-%d") if created_at else ""
                exp_date = p.get('expiration_date')
                exp_str = exp_date.strftime("%Y-%m-%d") if exp_date else "영구"
                
                df_rows.append({
                    "id": p['id'],
                    "제목": title_display,
                    "게시일자": date_str,
                    "작성자": p.get('author', ''),
                    "게시종료일": exp_str,
                    "is_important": is_imp
                })
            
            df = pd.DataFrame(df_rows)
            
            # 스타일 적용 (중요 게시물 파란색 + 굵은 글씨)
            def highlight_important_row(row):
                if row['is_important']:
                    return ['color: red; font-weight: bold;'] * len(row)
                return [''] * len(row)
            
            styled_df = df.style.apply(highlight_important_row, axis=1)
            
            return st.dataframe(
                styled_df,
                column_config={
                    "id": None, "is_important": None,
                    "제목": st.column_config.TextColumn("제목", width=600),
                    "작성자": st.column_config.TextColumn("작성자", width=80, help="작성자"),
                    "게시일자": st.column_config.TextColumn("게시일자", width=100, help="게시 시작일"),
                    "게시종료일": st.column_config.TextColumn("게시종료일", width=100, help="게시가 종료되는 날짜"),
                },
                column_order=["제목", "작성자", "게시일자", "게시종료일"],
                width="stretch", hide_index=True, on_select="rerun",
                selection_mode="single-row", height=600, 
                key=f"notice_board_list_table_{st.session_state['notice_list_key']}"
            )

        # 페이징 컨트롤 렌더링 함수
        def render_pagination_controls():
            col_prev, col_info, col_next = st.columns([1.2, 5, 1.2])
            with col_prev:
                if st.button("◀ 이전 페이지", disabled=(curr_page == 1), key="btn_prev_page", use_container_width=True):
                    st.session_state["notice_page"] -= 1
                    st.session_state["notice_list_key"] += 1
                    st.rerun()
            with col_info:
                st.markdown(f"<div style='text-align: center; line-height: 35px;'>Page {curr_page} / {total_pages}</div>", unsafe_allow_html=True)
            with col_next:
                if st.button("다음 페이지 ▶", disabled=(curr_page == total_pages), key="btn_next_page", use_container_width=True):
                    st.session_state["notice_page"] += 1
                    st.session_state["notice_list_key"] += 1
                    st.rerun()

        if view_mode == "list":
            st.markdown("### 📋 공지사항 목록")
            
            selection = render_notice_list(page_posts)
            render_pagination_controls()
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                st.session_state["selected_post_id"] = page_posts[idx]['id']
                st.session_state["notice_view_mode"] = "detail"
                st.query_params["notice_id"] = page_posts[idx]['id']
                st.rerun()
        
        else: # Detail View
            if st.button("⬅️ 목록으로 돌아가기"):
                st.session_state["notice_view_mode"] = "list"
                st.session_state["selected_post_id"] = None
                st.session_state["notice_list_key"] += 1
                st.session_state["notice_expander_state"] = False # [수정] 목록 복귀 시 작성 폼 닫기
                st.query_params.clear()
                st.rerun()

            post = next((p for p in visible_posts if p['id'] == selected_id), None)
            
            if post:
                
                # 수정 모드 확인
                is_editing = (st.session_state.get("edit_post_id") == post['id'])

                if is_editing:
                    with st.form(f"edit_form_{post['id']}"):
                        st.write("🛠️ **공지사항 수정**")
                        e_title = st.text_input("제목", value=post['title'])
                        e_content = st.text_area("내용", value=post['content'], height=100)
                        
                        c1, c2 = st.columns(2)
                        
                        # 사용자 목록 다시 로드
                        users_ref = db.collection("users").stream()
                        users_opts = [f"{u.to_dict().get('username')} ({u.to_dict().get('name')})" for u in users_ref]
                        target_options = ["전체 공지"] + users_opts
                        
                        # 기존 값 복원
                        default_sel = []
                        if post.get('target_type') == "전체공지":
                            default_sel = ["전체 공지"]
                        elif isinstance(post.get('target_value'), list):
                            default_sel = [t for t in post.get('target_value') if t in users_opts]
                        
                        e_selected_targets = c1.multiselect("공지 대상 선택", target_options, default=default_sel)

                        # [NEW] 게시 기간 수정
                        st.write("⏳ 게시 기간 설정")
                        curr_exp = post.get('expiration_date')
                        term_idx = 1 if curr_exp else 0
                        
                        ec_t1, ec_t2 = st.columns(2)
                        e_post_term = ec_t1.radio("게시 기간", ["영구 게시", "기간 설정"], index=term_idx, horizontal=True, key=f"e_term_{post['id']}")
                        e_expiration_date = None
                        
                        if e_post_term == "기간 설정":
                            default_d = datetime.date.today() + datetime.timedelta(days=7)
                            if curr_exp:
                                if isinstance(curr_exp, datetime.datetime):
                                    default_d = curr_exp.date()
                                elif isinstance(curr_exp, str):
                                    try: default_d = datetime.datetime.strptime(curr_exp[:10], "%Y-%m-%d").date()
                                    except: pass
                            
                            e_exp_date = ec_t2.date_input("게시 종료일", default_d, key=f"e_exp_d_{post['id']}")
                            e_expiration_date = datetime.datetime.combine(e_exp_date, datetime.time.max)

                        e_is_important = st.checkbox("중요(상단 고정)", value=post.get('is_important', False))
                        
                        # 첨부파일 처리
                        st.markdown("---")
                        has_file = bool(post.get('file_name'))
                        delete_file = False
                        if has_file:
                            st.info(f"현재 첨부파일: {post.get('file_name')}")
                            delete_file = st.checkbox("첨부파일 삭제", key=f"del_file_{post['id']}")
                        
                        new_file = st.file_uploader("새 첨부파일 업로드 (기존 파일 대체)", type=['png', 'jpg', 'jpeg', 'pdf', 'xlsx', 'txt'], key=f"new_file_{post['id']}")

                        c_btn1, c_btn2 = st.columns([1, 1])
                        if c_btn1.form_submit_button("수정 저장", type="primary"):
                            if not e_selected_targets:
                                st.error("공지 대상을 선택해주세요.")
                                st.stop()

                            if "전체 공지" in e_selected_targets:
                                e_target_type = "전체공지"
                                e_target_value = []
                            else:
                                e_target_type = "대상선택"
                                e_target_value = e_selected_targets

                            updates = {
                                "title": e_title,
                                "content": e_content,
                                "target_type": e_target_type,
                                "target_value": e_target_value,
                                "is_important": e_is_important,
                                "expiration_date": e_expiration_date
                            }
                            
                            # 파일 업데이트 로직
                            if new_file:
                                if new_file.size > 1024 * 1024:
                                    st.error("첨부파일은 1MB 이하여야 합니다.")
                                    st.stop()
                                file_bytes = new_file.read()
                                updates['file_data'] = base64.b64encode(file_bytes).decode('utf-8')
                                updates['file_name'] = new_file.name
                            elif delete_file:
                                updates['file_data'] = firestore.DELETE_FIELD
                                updates['file_name'] = firestore.DELETE_FIELD
                            
                            db.collection("posts").document(post['id']).update(updates)
                            st.session_state["edit_post_id"] = None
                            st.success("수정되었습니다.")
                            st.rerun()
                            
                        if c_btn2.form_submit_button("취소"):
                            st.session_state["edit_post_id"] = None
                            st.rerun()
                else:
                    # 상세 조회 뷰
                    # 대상 문자열 처리
                    target_str = "전체"
                    if post.get('target_type') == "대상선택":
                        t_vals = post.get('target_value', [])
                        if isinstance(t_vals, list):
                            if len(t_vals) > 1:
                                target_str = f"{t_vals[0].split(' (')[0]} 외 {len(t_vals)-1}명"
                            elif len(t_vals) == 1:
                                target_str = t_vals[0].split(' (')[0]
                            else:
                                target_str = "-"

                    # [NEW] 상세 뷰 스타일링
                    badge_html = ""
                    if post.get('is_important'):
                        badge_html = '<span class="notice-badge badge-important">중요</span>'
                    else:
                        badge_html = '<span class="notice-badge badge-normal">일반</span>'
                        
                    st.markdown(f"""
                    <div style="border-bottom: 2px solid #eee; padding-bottom: 10px; margin-bottom: 20px;">
                        <h3>{badge_html} {post['title']}</h3>
                        <div class="notice-meta">작성자: {post.get('author')} | 작성일: {post.get('created_at').strftime('%Y-%m-%d %H:%M') if post.get('created_at') else ''} | 대상: {target_str}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.markdown(f"""
                    <div style="background-color: #ffffff; padding: 20px; border-radius: 8px; border: 1px solid #e0e0e0; min-height: 300px; white-space: pre-wrap; color: #333; font-size: 1.05em; line-height: 1.6;">
                        {post['content']}
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 첨부파일 다운로드
                    if post.get('file_data') and post.get('file_name'):
                        b64_data = post['file_data']
                        file_name = post['file_name']
                        href = f'<a href="data:application/octet-stream;base64,{b64_data}" download="{file_name}">📎 첨부파일: {file_name} 다운로드</a>'
                        st.markdown(href, unsafe_allow_html=True)
                    
                    # 수정/삭제 버튼 (본인 또는 관리자만)
                    if current_role == "admin" or current_user_id == post.get("author_id"):
                        st.divider()
                        c_space, c_edit, c_del = st.columns([8, 1, 1])
                        with c_edit:
                            if st.button("수정", key=f"edit_btn_{post['id']}", use_container_width=True):
                                st.session_state["edit_post_id"] = post['id']
                                st.rerun()
                        with c_del:
                            if st.button("삭제", key=f"del_post_{post['id']}", use_container_width=True):
                                db.collection("posts").document(post['id']).delete()
                                st.session_state["notice_view_mode"] = "list"
                                st.session_state["selected_post_id"] = None
                                st.session_state["notice_list_key"] += 1
                                st.query_params.clear()
                                st.rerun()
            
            # [NEW] 상세 화면 하단에 목록 표시
            st.divider()
            st.markdown("### 📋 공지사항 목록")
            
            selection = render_notice_list(page_posts, current_selected_id=selected_id)
            render_pagination_controls()
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                new_id = page_posts[idx]['id']
                if new_id != selected_id:
                    st.session_state["selected_post_id"] = new_id
                    st.query_params["notice_id"] = new_id
                    st.rerun()
            else:
                # [수정] 선택 해제 시 목록으로 돌아가기
                st.session_state["notice_view_mode"] = "list"
                st.session_state["selected_post_id"] = None
                st.query_params.clear()
                st.rerun()
    else:
        st.info("등록된 공지사항이 없습니다.")

def render_schedule(db):
    st.title("🗓️ 업무일정 (Calendar)")
    
    current_user_name = st.session_state.get("user_name", "Unknown")
    current_role = st.session_state.get("role", "user")

    # 1. 달력 컨트롤 (년/월 선택)
    c1, c2, c3 = st.columns([1, 1, 4])
    today = datetime.date.today()
    
    if "cal_year" not in st.session_state: st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state: st.session_state["cal_month"] = today.month
    
    with c1:
        sel_year = st.number_input("년도", value=st.session_state["cal_year"], step=1, key="input_cal_year")
    with c2:
        sel_month = st.number_input("월", min_value=1, max_value=12, value=st.session_state["cal_month"], step=1, key="input_cal_month")
        
    # 2. 일정 데이터 조회
    # 해당 월의 시작일과 종료일 계산
    start_date = datetime.date(sel_year, sel_month, 1)
    last_day = calendar.monthrange(sel_year, sel_month)[1]
    end_date = datetime.date(sel_year, sel_month, last_day)
    
    # 문자열 비교를 위해 YYYY-MM-DD 형식으로 변환
    s_str = start_date.strftime("%Y-%m-%d")
    e_str = end_date.strftime("%Y-%m-%d")
    
    schedules_ref = db.collection("schedules").where("date", ">=", s_str).where("date", "<=", e_str).stream()
    
    # 날짜별 일정 매핑
    schedule_map = {}
    for doc in schedules_ref:
        d = doc.to_dict()
        d['id'] = doc.id
        d_date = d.get('date') # YYYY-MM-DD
        if d_date:
            day_int = int(d_date.split('-')[2])
            if day_int not in schedule_map:
                schedule_map[day_int] = []
            schedule_map[day_int].append(d)
            
    # 3. 달력 그리기 (HTML)
    cal = calendar.monthcalendar(sel_year, sel_month)
    
    # CSS 스타일
    st.markdown("""
    <style>
        .calendar-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        .calendar-table th { background-color: #f0f2f6; padding: 10px; text-align: center; border: 1px solid #ddd; }
        .calendar-table td { height: 120px; vertical-align: top; padding: 5px; border: 1px solid #ddd; width: 14.28%; }
        .day-number { font-weight: bold; margin-bottom: 5px; display: block; }
        
        /* 일정 아이템 스타일 */
        .sch-item { 
            font-size: 0.8em; 
            padding: 2px 4px; 
            margin-bottom: 2px; 
            border-radius: 3px; 
            cursor: pointer;
            position: relative; /* 툴팁 위치 기준 */
        }
        
        /* 텍스트 말줄임 처리를 위한 내부 클래스 */
        .sch-text {
            white-space: nowrap; 
            overflow: hidden; 
            text-overflow: ellipsis;
        }

        .sch-allday { background-color: #e6f3ff; color: #333; }
        .sch-time { background-color: #fff3cd; color: #856404; }
        .sch-urgent { background-color: #ffe6e6; color: #d93025; }
        .today { background-color: #fff9c4; }
        .weekend { color: #d93025; }

        /* 커스텀 툴팁 스타일 */
        .sch-item .tooltip-text {
            visibility: hidden;
            width: 250px;          /* 너비 확대 */
            background-color: #333;
            color: #fff;
            text-align: left;
            border-radius: 6px;
            padding: 10px;         /* 패딩 확대 */
            position: absolute;
            z-index: 1000;         /* z-index 높임 */
            bottom: 110%;          /* 아이템 위쪽에 표시 */
            left: 50%;
            margin-left: -125px;   /* 중앙 정렬 (너비의 절반) */
            opacity: 0;
            transition: opacity 0.2s;
            font-size: 1.1em;      /* 폰트 크기 확대 */
            line-height: 1.4;
            white-space: normal;   /* 줄바꿈 허용 */
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            pointer-events: none;  /* 마우스 이벤트 통과 */
        }

        .sch-item:hover .tooltip-text {
            visibility: visible;
            opacity: 1;
        }
        
        /* 툴팁 화살표 */
        .sch-item .tooltip-text::after {
            content: "";
            position: absolute;
            top: 100%;
            left: 50%;
            margin-left: -5px;
            border-width: 5px;
            border-style: solid;
            border-color: #333 transparent transparent transparent;
        }
    </style>
    """, unsafe_allow_html=True)
    
    html = '<table class="calendar-table">'
    html += '<tr><th class="weekend">일</th><th>월</th><th>화</th><th>수</th><th>목</th><th>금</th><th>토</th></tr>'
    
    for week in cal:
        html += '<tr>'
        for i, day in enumerate(week):
            if day == 0:
                html += '<td style="background-color: #f9f9f9;"></td>'
            else:
                is_today = (day == today.day and sel_month == today.month and sel_year == today.year)
                is_sunday = (i == 0)
                
                td_class = "today" if is_today else ""
                num_class = "weekend" if is_sunday else ""
                
                html += f'<td class="{td_class}">'
                html += f'<span class="day-number {num_class}">{day}</span>'
                
                if day in schedule_map:
                    # 정렬: 하루 종일(True) 우선, 그 다음 시간순
                    # is_all_day 필드가 없는 기존 데이터는 True(하루종일)로 취급
                    day_scheds = schedule_map[day]
                    day_scheds.sort(key=lambda x: (not x.get('is_all_day', True), x.get('time', '')))
                    
                    for sch in day_scheds:
                        is_urgent = (sch.get('type') == "긴급")
                        is_all_day = sch.get('is_all_day', True)
                        
                        # 스타일 클래스 결정 (긴급이 아니면 하루일정/시간설정 색상 구분)
                        base_class = "sch-allday" if is_all_day else "sch-time"
                        sch_class = "sch-urgent" if is_urgent else base_class
                        
                        icon = "🚨" if is_urgent else "🔹"
                        content = sch.get('content', '')
                        
                        # 시간 표시 처리
                        display_text = content
                        time_str = ""
                        if not sch.get('is_all_day', True):
                            time_str = sch.get('time', '')
                            if time_str:
                                display_text = f"({time_str}) {content}"
                        
                        # [수정] 커스텀 HTML 툴팁 적용
                        tooltip_html = f"<strong>[{sch.get('date')}] {sch.get('author')}</strong><br>"
                        if time_str: tooltip_html += f"시간: {time_str}<br>"
                        tooltip_html += f"내용: {content}"
                        
                        html += f'''
                        <div class="sch-item {sch_class}">
                            <div class="sch-text">{icon} {display_text}</div>
                            <span class="tooltip-text">{tooltip_html}</span>
                        </div>'''
                
                html += '</td>'
        html += '</tr>'
    html += '</table>'
    
    st.markdown(html, unsafe_allow_html=True)
    
    st.divider()
    
    # 4. 일정 관리 (추가/삭제)
    c_add, c_list = st.columns([1, 2])
    
    with c_add:
        st.subheader("➕ 일정 등록")
        # [수정] st.form 제거 (라디오 버튼 즉시 반응을 위해)
        s_date = st.date_input("날짜", datetime.date(sel_year, sel_month, today.day))
        
        # [NEW] 시간 설정 옵션
        time_opt = st.radio("시간 설정", ["하루일정", "시간 설정"], horizontal=True)
        s_time = None
        if time_opt == "시간 설정":
            s_time = st.time_input("시간", datetime.datetime.now().time())
            
        s_content = st.text_input("내용")
        s_type = st.selectbox("구분", ["일반", "긴급"])
        
        if st.button("일정 추가", type="primary"):
            if s_content:
                doc_data = {
                    "date": str(s_date),
                    "content": s_content,
                    "type": s_type,
                    "author": current_user_name,
                    "is_all_day": (time_opt == "하루일정")
                }
                if time_opt == "시간 설정" and s_time:
                    doc_data["time"] = s_time.strftime("%H:%M")
                    
                db.collection("schedules").add(doc_data)
                st.success("추가되었습니다.")
                st.rerun()
            else:
                st.warning("내용을 입력하세요.")

    with c_list:
        st.subheader(f"📋 {sel_month}월 일정 목록 (삭제)")
        # 현재 달력에 표시된 일정 목록 표시
        month_schedules = []
        for day in sorted(schedule_map.keys()):
            for sch in schedule_map[day]:
                month_schedules.append(sch)
        
        if month_schedules:
            for sch in month_schedules:
                col1, col2 = st.columns([5, 1])
                is_urgent = (sch.get('type') == "긴급")
                icon = "🚨" if is_urgent else "📅"
                
                # [수정] 표시 형식: 날짜 | 시간 | 작성자 | 내용
                date_str = sch['date']
                time_display = "하루일정"
                if not sch.get('is_all_day', True):
                    time_display = sch.get('time', '')
                
                author_str = sch.get('author', 'Unknown')
                content_str = sch['content']
                
                col1.markdown(f"**{date_str}** &nbsp; ` {time_display} ` &nbsp; **{author_str}**: {content_str}")
                
                # [수정] 작성자 본인 또는 관리자만 삭제 가능
                if current_user_name == author_str or current_role == 'admin':
                    # [NEW] 삭제 확인 로직
                    del_key = f"confirm_del_{sch['id']}"
                    if st.session_state.get(del_key):
                        if col2.button("✅", key=f"yes_{sch['id']}", help="삭제 확인"):
                            db.collection("schedules").document(sch['id']).delete()
                            del st.session_state[del_key]
                            st.rerun()
                        if col2.button("❌", key=f"no_{sch['id']}", help="취소"):
                            del st.session_state[del_key]
                            st.rerun()
                    else:
                        if col2.button("삭제", key=f"del_sch_cal_{sch['id']}"):
                            st.session_state[del_key] = True
                            st.rerun()
        else:
            st.info("📅 등록된 일정이 없습니다.")