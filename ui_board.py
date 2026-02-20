import streamlit as st
import pandas as pd
import datetime
import base64
import calendar
import uuid
from firebase_admin import firestore

def render_notice_board(db):
    st.title("공지사항")
    
    # [수정] 공지사항 배지 및 테이블 스타일 정의
    st.markdown("""
    <style>
        .notice-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; font-weight: bold; margin-right: 5px; }
        .badge-important { background-color: #ffebee; color: #c62828; }
        .badge-normal { background-color: #e3f2fd; color: #1565c0; }
        /* 데이터프레임 헤더 가운데 정렬 */
        .stDataFrame th {
            text-align: center !important;
        }
        .stDataFrame th > div {
            justify-content: center !important;
        }
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

    if "notice_list_key" not in st.session_state:
        st.session_state["notice_list_key"] = 0
    
    # [수정] URL 쿼리 파라미터 확인 (외부 링크 접속 시)
    if 'notice_id' in st.query_params:
        st.session_state["selected_post_id"] = st.query_params['notice_id']

    selected_id = st.session_state.get("selected_post_id")

    # [NEW] 검색 필터 세션 초기화
    if "n_search_author" not in st.session_state: st.session_state["n_search_author"] = ""
    if "n_search_keyword" not in st.session_state: st.session_state["n_search_keyword"] = ""
    if "notice_page" not in st.session_state: st.session_state["notice_page"] = 1

    # [NEW] 검색 UI
    with st.expander("공지사항 검색", expanded=False):
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
            
            t_type = p_data.get('target_type')
            t_val = p_data.get('target_value')
            author_id = p_data.get('author_id')
            
            is_visible = False
            
            # 1. 관리자나 작성자는 무조건 봄
            if current_role == "admin" or author_id == current_user_id:
                is_visible = True
            # 2. 대상선택인 경우 본인 포함 여부 확인
            elif t_type == "대상선택":
                if isinstance(t_val, list):
                    for target in t_val:
                        if target.startswith(f"{current_user_id} ("):
                            is_visible = True
                            break
            # 3. 그 외(전체공지, None, 빈값 등)는 모두 전체 공개로 간주
            else:
                is_visible = True
            
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

        # 페이징 컨트롤 렌더링 함수
        def render_pagination_controls():
            col_prev, col_info, col_next = st.columns([1.2, 5, 1.2])
            with col_prev:
                if st.button("◀ 이전 페이지", disabled=(curr_page == 1), key="btn_prev_page", use_container_width=True):
                    st.session_state["notice_page"] -= 1
                    st.session_state["selected_post_id"] = None # 페이지 이동 시 선택 해제
                    st.session_state["notice_list_key"] += 1
                    st.rerun()
            with col_info:
                st.markdown(f"<div style='text-align: center; line-height: 35px;'>Page {curr_page} / {total_pages}</div>", unsafe_allow_html=True)
            with col_next:
                if st.button("다음 페이지 ▶", disabled=(curr_page == total_pages), key="btn_next_page", use_container_width=True):
                    st.session_state["notice_page"] += 1
                    st.session_state["selected_post_id"] = None # 페이지 이동 시 선택 해제
                    st.session_state["notice_list_key"] += 1
                    st.rerun()

        # [NEW] 테이블 형태의 목록 렌더링 함수
        def render_notice_list(posts):
            df_rows = []
            for p in posts:
                is_imp = p.get('is_important', False)
                
                title_display = p['title']
                if p.get('file_name'):
                    title_display += " 📎"
                
                created_at = p.get('created_at')
                date_str = created_at.strftime("%Y-%m-%d") if created_at else ""
                exp_date = p.get('expiration_date')
                exp_str = exp_date.strftime("%Y-%m-%d") if exp_date else "영구"
                
                df_rows.append({
                    "id": p['id'], "is_important": is_imp, "제목": title_display,
                    "작성자": p.get('author', ''), "게시일": date_str, "게시종료일": exp_str,
                })
            
            if not df_rows: return None

            df = pd.DataFrame(df_rows)
            
            def highlight_important(row):
                return ['color: #c62828; font-weight: bold;'] * len(row) if row.is_important else [''] * len(row)

            styled_df = df.style.apply(highlight_important, axis=1)

            return st.dataframe(
                styled_df,
                column_config={
                    "id": None, "is_important": None,
                    "제목": st.column_config.TextColumn("제목", width="large"),
                    "작성자": st.column_config.TextColumn("작성자", width="small"),
                    "게시일": st.column_config.TextColumn("게시일", width="small"),
                    "게시종료일": st.column_config.TextColumn("게시종료일", width="small"),
                },
                column_order=["제목", "작성자", "게시일", "게시종료일"],
                hide_index=True, on_select="rerun", selection_mode="single-row",
                use_container_width=True,
                key=f"notice_board_list_table_{st.session_state['notice_list_key']}"
            )

        # --- [변경] 목록 상시 표시 ---
        st.markdown("### 공지사항 목록")
        
        selection = render_notice_list(page_posts)
        render_pagination_controls()
        
        # 목록에서 선택 시 ID 업데이트
        if selection and selection.selection.rows:
            idx = selection.selection.rows[0]
            # [FIX] 페이지 변경 등으로 인해 인덱스가 범위를 벗어나는 경우 방지
            if idx < len(page_posts):
                new_selected_id = page_posts[idx]['id']
                if new_selected_id != selected_id:
                    st.session_state["selected_post_id"] = new_selected_id
                    st.query_params["notice_id"] = new_selected_id
                    st.rerun()
        # [NEW] 사용자가 목록에서 선택을 해제했을 때 (체크 해제)
        elif selection and not selection.selection.rows:
            if selected_id is not None: # 상세 보기가 활성화된 상태에서만 실행
                st.session_state["selected_post_id"] = None
                st.query_params.clear()
                st.rerun()

        st.divider()

        # --- [변경] 하단 영역: 상세 내용 또는 글쓰기 폼 ---
        if not selected_id:
            # 선택된 글이 없을 때: 글쓰기 폼 표시
            with st.expander("새로운 공지사항 작성하기", expanded=st.session_state["notice_expander_state"]):
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
        
        else: # Detail View (선택된 글이 있을 때)
            c_back1, c_back2 = st.columns([6, 1])
            with c_back2:
                if st.button("닫기", use_container_width=True, help="상세 내용을 닫습니다."):
                    st.session_state["selected_post_id"] = None
                    st.session_state["notice_list_key"] += 1
                    st.query_params.clear()
                    st.rerun()

            post = next((p for p in visible_posts if p['id'] == selected_id), None)
            
            if post:
                
                # 수정 모드 확인
                is_editing = (st.session_state.get("edit_post_id") == post['id'])

                if is_editing:
                    with st.form(f"edit_form_{post['id']}"):
                        st.write("**공지사항 수정**")
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
                        href = f'<a href="data:application/octet-stream;base64,{b64_data}" download="{file_name}">첨부파일: {file_name} 다운로드</a>'
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
                                st.session_state["selected_post_id"] = None
                                st.session_state["notice_list_key"] += 1
                                st.query_params.clear()
                                st.rerun()

def render_schedule(db):
    st.title("업무일정 (Calendar)")
    
    current_user_name = st.session_state.get("user_name", "Unknown")
    current_role = st.session_state.get("role", "user")
    current_user_id = st.session_state.get("user_id", "") # For author check

    # [NEW] 일정 수정 모달 처리
    edit_id = st.query_params.get("edit_schedule_id")
    if edit_id:
        doc_ref = db.collection("schedules").document(edit_id)
        doc = doc_ref.get()
        if doc.exists:
            sch_to_edit = doc.to_dict()
            
            # 본인 또는 관리자만 수정 가능
            if sch_to_edit.get('author') == current_user_name or current_role == 'admin':
                with st.dialog("일정 수정"):
                    with st.form("edit_schedule_form"):
                        st.write(f"**{sch_to_edit.get('date')}** 일정 수정")
                        
                        # 기존 값 로드
                        is_all_day = sch_to_edit.get('is_all_day', True)
                        time_opt_index = 0 if is_all_day else 1
                        
                        new_time_opt = st.radio("시간 설정", ["하루 종일", "시간 지정"], index=time_opt_index, horizontal=True, key=f"edit_time_opt_{edit_id}")
                        
                        new_time = None
                        if new_time_opt == "시간 지정":
                            try:
                                default_time = datetime.datetime.strptime(sch_to_edit.get('time', '09:00'), "%H:%M").time()
                            except:
                                default_time = datetime.time(9, 0)
                            new_time = st.time_input("시간", value=default_time, key=f"edit_time_{edit_id}")

                        new_content = st.text_input("내용", value=sch_to_edit.get('content', ''))
                        
                        type_opts = ["일반", "긴급"]
                        type_idx = type_opts.index(sch_to_edit.get('type', '일반')) if sch_to_edit.get('type', '일반') in type_opts else 0
                        new_type = st.selectbox("구분", type_opts, index=type_idx, key=f"edit_type_{edit_id}")
                        
                        c1, c2 = st.columns(2)
                        if c1.form_submit_button("수정 저장", type="primary"):
                            updates = { "content": new_content, "type": new_type, "is_all_day": new_time_opt == "하루 종일" }
                            if new_time_opt == "시간 지정" and new_time:
                                updates["time"] = new_time.strftime("%H:%M")
                            else:
                                updates["time"] = firestore.DELETE_FIELD
                            
                            doc_ref.update(updates)
                            st.success("일정이 수정되었습니다.")
                            st.query_params.clear()
                            st.rerun()
                            
                        if c2.form_submit_button("닫기"):
                            st.query_params.clear()
                            st.rerun()
            else:
                with st.dialog("권한 없음"):
                    st.warning("이 일정을 수정할 권한이 없습니다.")
                    if st.button("닫기"):
                        st.query_params.clear()
                        st.rerun()
        else:
            with st.dialog("오류"):
                st.warning("수정할 일정을 찾을 수 없습니다. 삭제되었을 수 있습니다.")
                if st.button("닫기"):
                    st.query_params.clear()
                    st.rerun()

    # 1. 달력 컨트롤 (년/월 선택)
    today = datetime.date.today()
    
    if "cal_year" not in st.session_state: st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state: st.session_state["cal_month"] = today.month
    
    # [NEW] Admin holiday management UI
    if current_role == 'admin':
        with st.expander("특정일 관리 (관리자 전용)"):
            st.info("특정 기간을 지정하고 색상을 선택하여 달력에 표시합니다.")
            
            # Get holidays for the current year to display in a list
            sel_year_for_list = st.session_state["cal_year"]
            year_start = f"{sel_year_for_list}-01-01"
            year_end = f"{sel_year_for_list}-12-31"
            # [수정] 문서 ID(__name__) 대신 date 필드로 조회하여 오류 방지
            h_docs = db.collection("holidays").where("date", ">=", year_start).where("date", "<=", year_end).stream()
            
            current_holidays = {doc.id: doc.to_dict() for doc in h_docs}
            
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown("##### 특정일 등록")
                # [수정] 기간 선택 방식 변경 (하루/기간)
                h_date_mode = st.radio("기간 유형", ["하루 일정", "기간 일정"], horizontal=True, key="h_date_mode_input")
                
                h_dates = []
                if h_date_mode == "하루 일정":
                    d = st.date_input("날짜", datetime.date.today(), key="h_date_single")
                    h_dates = [d, d]
                else:
                    c_d1, c_d2 = st.columns(2)
                    s_d = c_d1.date_input("시작일", datetime.date.today(), key="h_date_start")
                    e_d = c_d2.date_input("종료일", datetime.date.today(), key="h_date_end")
                    h_dates = [s_d, e_d]

                h_name = st.text_input("특정일명", "휴일", key="h_name_input")
                
                h_display_mode = st.radio(
                    "표시 방식",
                    ("모든 날짜에 표시", "특정일자만 표시"),
                    horizontal=True,
                    help="기간 내에서 특정일명을 어떻게 표시할지 선택합니다.",
                    key="h_display_mode_input"
                )

                specific_date_to_add = None
                if h_display_mode == "특정일자만 표시":
                    date_options = []
                    if len(h_dates) == 2:
                        start_d, end_d = h_dates
                        if start_d <= end_d:
                            date_options = [start_d + datetime.timedelta(days=i) for i in range((end_d - start_d).days + 1)]
                    elif len(h_dates) == 1:
                        date_options = [h_dates[0]]
                    
                    if date_options:
                        specific_date_to_add = st.selectbox("표시할 특정일자 선택", date_options, format_func=lambda d: d.strftime("%Y-%m-%d"), key="h_specific_date_input")
                    else:
                        st.warning("기간을 먼저 올바르게 선택해주세요.")

                color_map = {"검정색": "#333333", "빨간색": "#d93025", "파란색": "#1a73e8", "초록색": "#1e8e3e", "주황색": "#f97d00", "보라색": "#9334e6"}
                h_color_name = st.selectbox("표시 색상", list(color_map.keys()), key="h_color_name_input")
                
                if st.button("등록"):
                    # [수정] 기간 내 모든 날짜를 대상으로 하되, 이름 표시 여부만 분기
                    dates_in_range = []
                    if len(h_dates) >= 1:
                        start_date = h_dates[0]
                        end_date = h_dates[1] if len(h_dates) == 2 else start_date
                        if start_date <= end_date:
                            for i in range((end_date - start_date).days + 1):
                                dates_in_range.append(start_date + datetime.timedelta(days=i))

                    if not dates_in_range:
                        st.error("기간을 올바르게 선택해주세요.")
                    elif h_display_mode == "특정일자만 표시" and not specific_date_to_add:
                        st.error("표시할 특정일자를 선택해주세요.")
                    else:
                        group_id = str(uuid.uuid4())
                        batch = db.batch()
                        for day in dates_in_range:
                            day_str = day.strftime("%Y-%m-%d")
                            doc_ref = db.collection("holidays").document(day_str)
                            
                            # 이름 결정: 모든 날짜 표시 모드이거나, 특정일자 모드에서 해당 날짜인 경우
                            name_to_save = h_name if (h_display_mode == "모든 날짜에 표시" or day == specific_date_to_add) else ""
                            
                            batch.set(doc_ref, {"name": name_to_save, "date": day_str, "color": color_map[h_color_name], "group_id": group_id})
                        batch.commit()
                        st.success(f"'{h_name}' 일정이 등록되었습니다.")
                        
                        # 입력 필드 초기화를 위해 세션 상태 삭제
                        keys_to_clear = ["h_date_mode_input", "h_date_single", "h_date_start", "h_date_end", "h_name_input", "h_display_mode_input", "h_specific_date_input", "h_color_name_input"]
                        for k in keys_to_clear:
                            if k in st.session_state: del st.session_state[k]
                        st.rerun()
            with c2:
                # [NEW] 공휴일 자동 등록 버튼
                if st.button(f"📅 {sel_year_for_list}년 공휴일 자동 등록 (Korea)", use_container_width=True, help="대한민국 공휴일을 자동으로 가져와 등록합니다."):
                    try:
                        import holidays
                    except ImportError:
                        import subprocess
                        import sys
                        st.warning("라이브러리(holidays)가 없어 자동 설치를 시도합니다...")
                        try:
                            subprocess.check_call([sys.executable, "-m", "pip", "install", "holidays"])
                            import holidays
                        except Exception:
                            st.error("❌ 'holidays' 라이브러리 설치에 실패했습니다. 터미널에서 `pip install holidays`를 실행해주세요.")
                            st.stop()

                    try:
                        kr_holidays = holidays.KR(years=sel_year_for_list)
                        
                        batch = db.batch()
                        added_count = 0
                        
                        # 현재 등록된 날짜 집합 (중복 방지)
                        existing_dates = set()
                        for h in current_holidays.values():
                            existing_dates.add(h.get('date'))
                            
                        for date, name in kr_holidays.items():
                            d_str = str(date)
                            if d_str not in existing_dates:
                                doc_ref = db.collection("holidays").document(d_str)
                                batch.set(doc_ref, {
                                    "name": name,
                                    "date": d_str,
                                    "color": "#d93025", # 빨간색
                                    "group_id": f"auto_{d_str}"
                                })
                                added_count += 1
                        
                        if added_count > 0:
                            batch.commit()
                            st.success(f"{added_count}일의 공휴일이 등록되었습니다.")
                            st.rerun()
                        else:
                            st.info("추가할 공휴일이 없습니다 (이미 등록됨).")
                            
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

                # [NEW] 그룹화 로직
                holiday_groups = {}
                if current_holidays:
                    for h_date_str, h_data in sorted(current_holidays.items()):
                        gid = h_data.get('group_id', f"single_{h_date_str}")
                        if gid not in holiday_groups:
                            holiday_groups[gid] = {'name': '', 'color': h_data.get('color', '#000'), 'dates': []}
                        holiday_groups[gid]['dates'].append(h_date_str)
                        # 그룹 내 이름이 있는 항목을 찾아 대표 이름으로 설정
                        if h_data.get('name'):
                            holiday_groups[gid]['name'] = h_data.get('name')
                    
                # [수정] 목록을 접었다 펼칠 수 있도록 expander 적용
                with st.expander(f"📋 {sel_year_for_list}년 등록된 특정일 목록", expanded=True):
                    if holiday_groups:
                        # 그룹별 표시
                        # 날짜순 정렬을 위해 각 그룹의 첫 번째 날짜 기준 정렬
                        sorted_groups = sorted(holiday_groups.items(), key=lambda x: sorted(x[1]['dates'])[0])
                        
                        for gid, info in sorted_groups:
                            dates = sorted(info['dates'])
                            start_d = dates[0]
                            end_d = dates[-1]
                            date_disp = f"{start_d} ~ {end_d}" if start_d != end_d else start_d
                            
                            hc1, hc2 = st.columns([3, 1])
                            # 색상 적용하여 표시
                            hc1.markdown(f"<span style='color:{info['color']};'>●</span> {date_disp}: {info['name']}", unsafe_allow_html=True)
                            
                            if hc2.button("삭제", key=f"del_h_grp_{gid}"):
                                batch = db.batch()
                                for d_str in dates:
                                    batch.delete(db.collection("holidays").document(d_str))
                                batch.commit()
                                st.success(f"삭제되었습니다.")
                                st.rerun()
                    else:
                        st.info("등록된 특정일이 없습니다.")
        st.divider()

    # [수정] 달력 컨트롤 및 필터 레이아웃 변경
    c_header_left, c_header_center, c_header_right = st.columns([1, 3, 1])
    
    with c_header_left:
        if st.button("오늘날짜보기", key="btn_today", use_container_width=True, help="오늘 날짜가 속한 달로 이동합니다."):
            today = datetime.date.today()
            st.session_state["cal_year"] = today.year
            st.session_state["cal_month"] = today.month
            st.rerun()

    with c_header_center:
        # 중앙 정렬을 위한 컬럼 분할 (이전년, 이전월, 현재, 다음월, 다음년) - 간격 조정을 위해 spacer 추가
        _, nc1, nc2, nc3, nc4, nc5, _ = st.columns([1.5, 0.3, 0.3, 1.2, 0.3, 0.3, 1.5])
        with nc1:
            if st.button("«", key="btn_prev_year", help="이전 년도"):
                st.session_state["cal_year"] -= 1
                st.rerun()
        with nc2:
            if st.button("◀", key="btn_prev_month", help="이전 달"):
                st.session_state["cal_month"] -= 1
                if st.session_state["cal_month"] < 1:
                    st.session_state["cal_month"] = 12
                    st.session_state["cal_year"] -= 1
                st.rerun()
        with nc3:
            st.markdown(f"<h3 style='text-align: center; margin: 0; padding-top: 5px;'>{st.session_state['cal_year']}. {st.session_state['cal_month']:02d}</h3>", unsafe_allow_html=True)
        with nc4:
            if st.button("▶", key="btn_next_month", help="다음 달"):
                st.session_state["cal_month"] += 1
                if st.session_state["cal_month"] > 12:
                    st.session_state["cal_month"] = 1
                    st.session_state["cal_year"] += 1
                st.rerun()
        with nc5:
            if st.button("»", key="btn_next_year", help="다음 년도"):
                st.session_state["cal_year"] += 1
                st.rerun()

    with c_header_right:
        # [NEW] 내 일정 필터
        show_my_only = st.checkbox("내가 등록한 일정만 보기", key="sch_filter_mine")

    sel_year = st.session_state["cal_year"]
    sel_month = st.session_state["cal_month"]
        
    # 2. 일정 데이터 조회
    # 해당 월의 시작일과 종료일 계산
    start_date = datetime.date(sel_year, sel_month, 1)
    last_day = calendar.monthrange(sel_year, sel_month)[1]
    end_date = datetime.date(sel_year, sel_month, last_day)
    
    # 문자열 비교를 위해 YYYY-MM-DD 형식으로 변환
    s_str = start_date.strftime("%Y-%m-%d")
    e_str = end_date.strftime("%Y-%m-%d")
    
    # [NEW] Fetch holiday data
    # [수정] 문서 ID(__name__) 대신 date 필드로 조회
    holidays_ref = db.collection("holidays").where("date", ">=", s_str).where("date", "<=", e_str).stream()
    holiday_map = {doc.id: doc.to_dict() for doc in holidays_ref}

    # [수정] 일정 데이터 조회 (필터 적용)
    schedules_query = db.collection("schedules").where("date", ">=", s_str).where("date", "<=", e_str)
    
    schedules_ref = schedules_query.stream()
    
    # 날짜별 일정 매핑
    schedule_map = {}
    for doc in schedules_ref:
        d = doc.to_dict()
        d['id'] = doc.id
        
        # [NEW] 메모리 상에서 작성자 필터링 (복합 인덱스 오류 방지)
        if show_my_only and d.get('author') != current_user_name:
            continue
            
        d_date = d.get('date') # YYYY-MM-DD
        if d_date:
            day_int = int(d_date.split('-')[2])
            if day_int not in schedule_map:
                schedule_map[day_int] = []
            schedule_map[day_int].append(d)
            
    # 3. 달력 그리기 (HTML)
    # [FIX] 기본 calendar.monthcalendar는 월요일 시작이므로, 일요일(6) 시작으로 변경하여 HTML 헤더와 맞춤
    cal = calendar.Calendar(firstweekday=6).monthdayscalendar(sel_year, sel_month)
    
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
        .weekend { color: #d93025; } /* 주말만 빨간색 */

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
                # [NEW] Check for holiday
                current_date_str = f"{sel_year}-{sel_month:02d}-{day:02d}"
                is_holiday = current_date_str in holiday_map
                
                td_class = "today" if is_today else ""
                html += f'<td class="{td_class}">'
                
                # [수정] 날짜 숫자 스타일링 (휴일 우선)
                if is_holiday:
                    holiday_color = holiday_map.get(current_date_str, {}).get('color', '#d93025')
                    holiday_name = holiday_map.get(current_date_str, {}).get('name', '')
                    html += f'<span class="day-number" style="color: {holiday_color}; font-weight: bold;">{day}</span>'
                    html += f'<span style="color: {holiday_color}; font-size: 0.8em; font-weight: bold; margin-left: 5px;">{holiday_name}</span>'
                elif is_sunday:
                    html += f'<span class="day-number weekend">{day}</span>'
                else:
                    html += f'<span class="day-number">{day}</span>'
                
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
                        
                        # [NEW] 수정 기능 추가: 본인 또는 관리자만 클릭 가능
                        can_edit = (sch.get('author') == current_user_name or current_role == 'admin')
                        onclick_attr = f"onclick=\"window.location.search='?edit_schedule_id={sch['id']}'\"" if can_edit else ""
                        cursor_style = "cursor: pointer;" if can_edit else "cursor: default;"
                        title_attr = "title='클릭하여 수정'" if can_edit else ""

                        html += f'''
                        <div class="sch-item {sch_class}" style="{cursor_style}" {onclick_attr} {title_attr}>
                            <div class="sch-text">{icon} {display_text}</div>
                            <span class="tooltip-text">{tooltip_html}</span>
                        </div>'''

                html += '</td>'
        html += '</tr>'
    html += '</table>'
    
    st.markdown(html, unsafe_allow_html=True)
    
    st.divider()
    
    # 4. 일정 관리 (추가/삭제) - [수정] 레이아웃 변경
    st.subheader(f"{sel_month}월 일정 목록")
    
    final_schedules = []

    # 1. 특정일(휴일) 데이터 처리 (미리 병합)
    holiday_groups_map = {}
    for h_date_str, h_data in holiday_map.items():
        h_year, h_month, _ = map(int, h_date_str.split('-'))
        if h_year == sel_year and h_month == sel_month:
            gid = h_data.get('group_id', f"single_h_{h_date_str}")
            if gid not in holiday_groups_map:
                holiday_groups_map[gid] = {'dates': [], 'name': '', 'color': h_data.get('color', '#d93025')}
            holiday_groups_map[gid]['dates'].append(h_date_str)
            if h_data.get('name'):
                holiday_groups_map[gid]['name'] = h_data.get('name')
    
    for gid, info in holiday_groups_map.items():
        dates = sorted(info['dates'])
        if not dates: continue
        
        holiday_sch = {
            'id': f"holiday_grp_{gid}", 'date': dates[0], 'end_date': dates[-1],
            'content': info.get('name'), 'author': '관리자', 'is_all_day': True,
            'type': '긴급', 'color': info.get('color', '#d93025'),
            'is_holiday': True, 'merged_ids': [] 
        }
        final_schedules.append(holiday_sch)
    
    # 2. 일반 일정 데이터 처리 (병합 로직 적용)
    raw_schedules = [sch for day in sorted(schedule_map.keys()) for sch in schedule_map[day]]
    raw_schedules.sort(key=lambda x: (x.get('date', ''), x.get('time', '00:00')))
    
    merged_normal_schedules = []
    if raw_schedules:
        curr = raw_schedules[0].copy()
        curr['end_date'] = curr['date']
        curr['merged_ids'] = [curr['id']]
        
        for next_sch in raw_schedules[1:]:
            is_same_meta = (curr['content'] == next_sch['content'] and curr.get('author') == next_sch.get('author') and curr.get('type') == next_sch.get('type') and curr.get('time') == next_sch.get('time'))
            curr_gid, next_gid = curr.get('group_id'), next_sch.get('group_id')
            is_same_group = (curr_gid is not None) and (curr_gid == next_gid)
            
            is_consecutive = False
            try:
                is_consecutive = (datetime.datetime.strptime(next_sch['date'], "%Y-%m-%d").date() - datetime.datetime.strptime(curr['end_date'], "%Y-%m-%d").date()).days == 1
            except: pass
            
            should_merge = is_same_meta and (is_same_group or (curr_gid is None and next_gid is None and is_consecutive))
            
            if should_merge:
                curr['end_date'] = next_sch['date']
                curr['merged_ids'].append(next_sch['id'])
            else:
                merged_normal_schedules.append(curr)
                curr = next_sch.copy()
                curr['end_date'] = curr['date']
                curr['merged_ids'] = [curr['id']]
        merged_normal_schedules.append(curr)
        
    final_schedules.extend(merged_normal_schedules)
    final_schedules.sort(key=lambda x: (x.get('date', ''), x.get('time', '00:00')))
    
    if final_schedules:
        for sch in final_schedules:
            col1, col2 = st.columns([5, 1])
            date_str = f"{sch['date']} ~ {sch['end_date']}" if sch['date'] != sch['end_date'] else sch['date']
            time_display = "하루일정" if sch.get('is_all_day', True) else sch.get('time', '')
            author_str, content_str, custom_color = sch.get('author', 'Unknown'), sch['content'], sch.get('color', None)
            
            if sch.get('is_holiday'):
                icon = f'<span style="color:{custom_color}; font-weight:bold;">●</span>'
                col1.markdown(f"{icon} <span style='color:{custom_color}; font-weight:bold;'>{date_str}</span> &nbsp; <span style='color:{custom_color};'>{content_str}</span>", unsafe_allow_html=True)
            else:
                icon = "🚨" if sch.get('type') == "긴급" else "📅"
                col1.markdown(f"{icon} **{date_str}** &nbsp; ` {time_display} ` &nbsp; **{author_str}**: {content_str}", unsafe_allow_html=True)
            
            if not sch.get('is_holiday') and (current_user_name == author_str or current_role == 'admin'):
                del_key = f"confirm_del_{sch['id']}"
                if st.session_state.get(del_key):
                    if col2.button("✅", key=f"yes_{sch['id']}", help="삭제 확인"):
                        batch = db.batch()
                        for mid in sch['merged_ids']: batch.delete(db.collection("schedules").document(mid))
                        batch.commit()
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

    st.divider()

    with st.expander("일정 등록하기"):
        # [수정] 일정 등록 방식 개선 (라디오 버튼으로 명확하게 분리)
        sch_mode = st.radio("일정 유형", ["하루 일정", "기간 일정"], horizontal=True)
        
        s_start_date = None
        s_end_date = None
        s_time = None
        is_all_day = True
        
        if sch_mode == "하루 일정":
            c1, c2 = st.columns(2)
            s_start_date = c1.date_input("날짜", datetime.date(sel_year, sel_month, today.day))
            s_end_date = s_start_date
            
            # [수정] 시간 설정 UI 배치 변경 (라디오 버튼 옆에 시간 입력)
            with c2:
                st.write("시간 설정")
                tc1, tc2 = st.columns([2, 1])
                time_opt = tc1.radio("시간 설정", ["하루 종일", "시간 지정"], horizontal=True, label_visibility="collapsed")
                if time_opt == "시간 지정":
                    s_time = tc2.time_input("시간", datetime.datetime.now().time(), label_visibility="collapsed")
                    is_all_day = False
        else: # 기간 일정
            c1, c2 = st.columns(2)
            s_start_date = c1.date_input("시작일", datetime.date(sel_year, sel_month, today.day))
            s_end_date = c2.date_input("종료일", datetime.date(sel_year, sel_month, today.day) + datetime.timedelta(days=1))
            st.info("💡 기간 일정은 '하루일정'으로 고정됩니다.")
            
        s_content = st.text_input("내용")
        s_type = st.selectbox("구분", ["일반", "긴급"])
        
        if st.button("일정 추가", type="primary"):
            if s_content:
                # 유효성 검사
                if sch_mode == "기간 일정" and s_start_date > s_end_date:
                    st.error("종료일이 시작일보다 앞설 수 없습니다.")
                    st.stop()

                batch = db.batch()
                # 기간 일정인 경우 그룹 ID 생성 (하루 일정이라도 시작!=종료일 수 없지만 로직상 분리)
                is_range = (sch_mode == "기간 일정" and s_start_date != s_end_date)
                group_id = str(uuid.uuid4()) if is_range else None
                
                target_dates = []
                if is_range:
                    for i in range((s_end_date - s_start_date).days + 1):
                        target_dates.append(s_start_date + datetime.timedelta(days=i))
                else:
                    target_dates.append(s_start_date)
                
                for d in target_dates:
                    doc_ref = db.collection("schedules").document()
                    doc_data = {
                        "date": str(d),
                        "content": s_content,
                        "type": s_type,
                        "author": current_user_name,
                        "is_all_day": is_all_day,
                        "group_id": group_id
                    }
                    if not is_all_day and s_time:
                        doc_data["time"] = s_time.strftime("%H:%M")
                    batch.set(doc_ref, doc_data)
                
                batch.commit()
                st.success("추가되었습니다.")
                st.rerun()
            else:
                st.warning("내용을 입력하세요.")