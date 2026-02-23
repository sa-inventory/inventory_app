import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import get_partners, generate_report_html, get_common_codes, manage_code_with_code

def render_weaving(db, sub_menu=None, readonly=False):
    st.header("제직 현황" if not readonly else "제직 조회 (Read-Only)")
    if "weaving_df_key" not in st.session_state:
        st.session_state["weaving_df_key"] = 0
    st.info("발주된 건을 확인하고 제직 작업을 지시하거나, 완료된 건을 염색 공정으로 넘깁니다.")

    # [공통] 제직기 설정 가져오기 (작업일지 등에서도 사용됨)
    machines_docs = list(db.collection("machines").order_by("machine_no").stream())
    
    # [수정] 데이터가 없거나 오류 발생 시 기본값 처리
    machines_data = []
    if not machines_docs:
        # 설정이 없으면 기본 1~9호대 가상 데이터 사용 (호환성 유지)
        machines_data = [{"machine_no": i, "name": f"{i}호대", "model": "", "note": ""} for i in range(1, 10)]
    else:
        machines_data = [d.to_dict() for d in machines_docs]
    
    # [수정] 작업일지와 생산일지에서는 상단 대시보드 숨김
    busy_machines = {} # 대시보드 미표시 시에도 아래 로직에서 참조할 수 있으므로 초기화
    
    if sub_menu not in ["작업일지", "생산일지"]:
        # [수정] st.expander를 사용하여 접고 펼 수 있도록 변경
        with st.expander("제직기별 제직 현황", expanded=True):
            # 1. 제직기별 제직 현황 (Dashboard)
            # 현재 가동 중인 제직기 정보 가져오기
            running_docs = db.collection("orders").where("status", "==", "제직중").stream()
            for doc in running_docs:
                d = doc.to_dict()
                m_no = d.get("machine_no")
                if m_no:
                    busy_machines[str(m_no)] = d
                    
            # 제직기 상태 표시 (한 줄에 5개씩 자동 줄바꿈)
            cols_per_row = 5
            for i in range(0, len(machines_data), cols_per_row):
                cols = st.columns(cols_per_row)
                for j in range(cols_per_row):
                    if i + j < len(machines_data):
                        m = machines_data[i+j]
                        m_no = str(m['machine_no'])
                        m_name = m['name']
                        # [수정] 모델명 제거하고 비고만 표시
                        m_desc = m.get('note', '').strip()
                        
                        with cols[j]:
                            if m_no in busy_machines:
                                item = busy_machines[m_no]
                                roll_cnt = item.get('weaving_roll_count', 0)
                                # 진행률 표시
                                cur_roll = item.get('completed_rolls', 0) + 1
                                # [수정] 발주처 표시 추가 (발주처 / 품명 / 롤정보 / 수량)
                                st.error(f"**{m_name}**\n\n{item.get('customer', '')}  \n{item.get('name')} ({cur_roll}/{roll_cnt}롤) / {int(item.get('stock', 0)):,}장")
                            else:
                                st.success(f"**{m_name}**\n\n대기중\n\n{m_desc}")
        
        st.divider()

    # --- 1. 제직대기 탭 ---
    if sub_menu == "제직대기 목록":
        st.subheader("제직 대기 목록")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (제직대기)
        if "key_weaving_wait" not in st.session_state:
            st.session_state["key_weaving_wait"] = 0
            
        # [NEW] 검색 UI 추가
        with st.expander("🔍 검색 및 필터", expanded=True):
            c_f1, c_f2, c_f3 = st.columns([1.2, 1, 2])
            today = datetime.date.today()
            # 기간 검색 (접수일 기준) - 기본 3개월
            s_date_range = c_f1.date_input("접수일 기간", [today - datetime.timedelta(days=90), today], key="weav_wait_date_range")
            
            search_criteria = c_f2.selectbox("검색 기준", ["전체", "발주처", "제품명", "제품종류"], key="weav_wait_criteria")
            search_keyword = c_f3.text_input("검색어 입력", key="weav_wait_keyword")

        # '제직대기' 상태인 건만 가져오기 (발주현황에서 '제직대기'로 변경된 건)
        docs = db.collection("orders").where("status", "==", "제직대기").stream()
        rows = []
        
        # 날짜 필터링 준비
        start_dt, end_dt = None, None
        if len(s_date_range) == 2:
            start_dt = datetime.datetime.combine(s_date_range[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date_range[1], datetime.time.max)
        elif len(s_date_range) == 1:
            start_dt = datetime.datetime.combine(s_date_range[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date_range[0], datetime.time.max)

        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (접수일 기준)
            if start_dt and end_dt:
                d_date = d.get('date')
                if d_date:
                    if d_date.tzinfo: d_date = d_date.replace(tzinfo=None)
                    if not (start_dt <= d_date <= end_dt): continue
                else:
                    continue
            
            rows.append(d)
        
        if rows:
            df = pd.DataFrame(rows)
            
            # 2. 키워드 검색 필터
            if search_keyword:
                search_keyword = search_keyword.lower()
                if search_criteria == "전체":
                     mask = df.apply(lambda x: search_keyword in str(x.get('customer', '')).lower() or
                                              search_keyword in str(x.get('name', '')).lower() or
                                              search_keyword in str(x.get('product_type', '')).lower() or
                                              search_keyword in str(x.get('order_no', '')).lower() or
                                              search_keyword in str(x.get('note', '')).lower(), axis=1)
                     df = df[mask]
                elif search_criteria == "발주처":
                    df = df[df['customer'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품명":
                    df = df[df['name'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품종류":
                    df = df[df['product_type'].astype(str).str.lower().str.contains(search_keyword, na=False)]

            # 날짜 포맷팅
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            if 'delivery_req_date' in df.columns:
                df['delivery_req_date'] = pd.to_datetime(df['delivery_req_date'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
            
            col_map = {
                "order_no": "발주번호", "status": "상태", "customer": "발주처", "name": "제품명", 
                "product_type": "제품종류", "weaving_type": "제품종류(구)", "yarn_type": "사종", "color": "색상", 
                "stock": "수량", "weight": "중량", "size": "사이즈", "date": "접수일", "delivery_req_date": "납품요청일"
            }
            display_cols = ["order_no", "status", "customer", "name", "stock", "product_type", "weaving_type", "yarn_type", "color", "weight", "size", "date", "delivery_req_date"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 제직기를 배정할 항목을 선택하세요. (다중 선택 가능)")
            # key="df_waiting" 추가로 사이드바 먹통 현상 해결
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="multi-row", key=f"df_waiting_{st.session_state['key_weaving_wait']}")
            
            if selection.selection.rows:
                if readonly:
                    st.info("🔒 조회 전용 모드입니다. (수정 불가)")
                else:
                    idx = selection.selection.rows[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                    
                    st.divider()
                    st.markdown(f"### 제직기 배정: **{sel_row['name']}**")
                    
                    if len(selection.selection.rows) > 1:
                        st.warning("⚠️ 여러 항목이 선택되었습니다. 현재 제직기 배정은 목록의 **첫 번째 항목**에 대해서만 수행됩니다.")

                    with st.form("weaving_start_form"):
                        c1, c2, c3, c4 = st.columns(4)
                        
                        # 제직기 선택 (사용 중인 것은 표시)
                        # [수정] 제직기 명칭만 표시하도록 변경
                        m_display_map = {} # "표시명": "호기번호" 매핑
                        m_options = []
                        for m in machines_data:
                            m_no = str(m['machine_no'])
                            m_name = m['name']
                            if m_no in busy_machines:
                                display_str = f"{m_name} (사용중)"
                            else:
                                display_str = m_name
                            m_options.append(display_str)
                            m_display_map[display_str] = m_no
                        
                        s_machine = c1.selectbox("제직기 선택", m_options)
                        s_date = c2.date_input("시작일자", datetime.date.today(), format="YYYY-MM-DD")
                        s_time = c3.time_input("시작시간", datetime.datetime.now().time())
                        s_roll = c4.number_input("제직롤수량", min_value=1, step=1)
                        
                        if st.form_submit_button("제직 시작"):
                            sel_m_no = m_display_map.get(s_machine)
                            if sel_m_no in busy_machines:
                                st.error(f"⛔ 해당 제직기는 이미 작업 중입니다!")
                            else:
                                start_dt = datetime.datetime.combine(s_date, s_time)
                                db.collection("orders").document(sel_id).update({
                                    "status": "제직중",
                                    "machine_no": int(sel_m_no),
                                    "weaving_start_time": start_dt,
                                    "weaving_roll_count": s_roll,
                                    "completed_rolls": 0
                                })
                                st.success(f"제직을 시작합니다.")
                                st.session_state["key_weaving_wait"] += 1 # 목록 선택 초기화
                                st.rerun()
                
                # 발주접수로 되돌리기 기능 추가
                st.divider()
                if st.button("🚫 발주접수로 되돌리기", key="back_to_order_waiting"):
                    db.collection("orders").document(sel_id).update({"status": "발주접수"})
                    st.success("발주접수 상태로 되돌렸습니다.")
                    st.session_state["key_weaving_wait"] += 1
                    st.rerun()
        else:
            st.info("대기 중인 작업이 없습니다.")

    # --- 2. 제직중 탭 ---
    elif sub_menu == "제직중 목록":
        st.subheader("제직중 목록")
        
        # [추가] 작업 결과 피드백 메시지 표시 (저장 후 리런되어도 메시지 유지)
        if st.session_state.get("weaving_msg"):
            st.success(st.session_state["weaving_msg"])
            st.session_state["weaving_msg"] = None
            
        docs = db.collection("orders").where("status", "==", "제직중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            if 'weaving_start_time' in df.columns:
                df['weaving_start_time'] = df['weaving_start_time'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            # 진행률 표시를 위해 컬럼 확보
            if 'completed_rolls' not in df.columns: df['completed_rolls'] = 0
            
            # [NEW] 롤 진행 상황 표시 (예: 1/3)
            df['roll_progress'] = df.apply(lambda x: f"{int(x.get('completed_rolls', 0) + 1)}/{int(x.get('weaving_roll_count', 1))}", axis=1)
            
            col_map = {
                "order_no": "발주번호", "machine_no": "제직기", "weaving_start_time": "시작시간",
                "customer": "발주처", "name": "제품명", "stock": "수량", "roll_progress": "롤진행(현재/총)"
            }
            display_cols = ["machine_no", "order_no", "customer", "name", "stock", "roll_progress", "weaving_start_time"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 완료 처리할 항목을 선택하세요.")
            # key="df_weaving" 추가
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_weaving_{st.session_state['weaving_df_key']}")
            
            if selection.selection.rows:
                if readonly:
                    st.info("🔒 조회 전용 모드입니다. (수정 불가)")
                else:
                    idx = selection.selection.rows[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                    
                    # [NEW] 잔여 수량 계산 및 실시간 중량 계산 로직
                    
                    # 1. 현재까지 생산된 롤들의 수량 합계 계산 (형제 문서 조회)
                    child_rolls = db.collection("orders").where("parent_id", "==", sel_id).stream()
                    accumulated_stock = 0
                    for r in child_rolls:
                        accumulated_stock += int(r.to_dict().get('real_stock', 0))
                    
                    total_order_stock = int(sel_row.get('stock', 0))
                    remaining_stock = max(0, total_order_stock - accumulated_stock)
                    
                    # 기본 중량 (g)
                    base_weight = int(sel_row.get('weight', 0)) if not pd.isna(sel_row.get('weight')) else 0
                    
                    # 세션 스테이트 키 (아이템별 고유)
                    ss_stock_key = f"ws_stock_{sel_id}"
                    ss_kg_key = f"ws_kg_{sel_id}"
                    
                    # 세션 초기화 (처음 선택 시 잔여 수량으로 설정)
                    if ss_stock_key not in st.session_state:
                        st.session_state[ss_stock_key] = remaining_stock
                        st.session_state[ss_kg_key] = float((remaining_stock * base_weight) / 1000)
                    
                    # 콜백 함수: 수량 변경 시 중량 자동 계산
                    def on_stock_change():
                        new_stock = st.session_state[ss_stock_key]
                        st.session_state[ss_kg_key] = float((new_stock * base_weight) / 1000)

                    st.divider()
                    st.markdown(f"### 제직 완료 처리: **{sel_row['name']}**")
                    
                    cur_completed = int(sel_row.get('completed_rolls', 0)) if not pd.isna(sel_row.get('completed_rolls')) else 0
                    total_rolls = int(sel_row.get('weaving_roll_count', 1)) if not pd.isna(sel_row.get('weaving_roll_count')) else 1
                    next_roll_no = cur_completed + 1
                    
                    if total_rolls > 1:
                        st.info(f"📢 현재 **{total_rolls}롤 중 {next_roll_no}번째 롤** 작업 중입니다. (누적 생산: {accumulated_stock}장 / 잔여: {remaining_stock}장)")
                    else:
                        st.info(f"📢 **단일 롤(1/1)** 작업 중입니다. (잔여: {remaining_stock}장)")
                    
                    # [변경] st.form 제거 -> 실시간 인터랙션 지원
                    st.write("생산 실적을 입력하세요.")
                    c1, c2 = st.columns(2)
                    end_date = c1.date_input("제직완료일", datetime.date.today(), key=f"wd_{sel_id}")
                    end_time = c2.time_input("완료시간", datetime.datetime.now().time(), key=f"wt_{sel_id}")
                    
                    c3, c4 = st.columns(2)
                    # 중량(g)
                    real_weight_g = c3.number_input("중량(g)", value=base_weight, step=1, format="%d", key=f"ww_{sel_id}")
                    # 생산매수(장) - 변경 시 on_stock_change 호출
                    real_stock_val = c4.number_input("생산매수(장)", min_value=0, step=1, format="%d", key=ss_stock_key, on_change=on_stock_change)
                    
                    c5, c6 = st.columns(2)
                    # 생산중량(kg) - 자동 계산되지만 수정 가능
                    prod_weight_val = c5.number_input("생산중량(kg)", min_value=0.0, step=0.1, format="%.1f", key=ss_kg_key)
                    # 평균중량(g)
                    avg_weight_val = c6.number_input("평균중량(g)", value=base_weight, step=1, format="%d", key=f"wa_{sel_id}")
                    
                    if st.button("제직 완료 저장", type="primary"):
                        end_dt = datetime.datetime.combine(end_date, end_time)
                        
                        # 1. 롤 데이터 생성 (새 문서)
                        parent_doc = db.collection("orders").document(sel_id).get().to_dict()
                        new_roll_doc = parent_doc.copy()
                        
                        new_roll_doc['status'] = "제직완료"
                        new_roll_doc['order_no'] = f"{parent_doc.get('order_no')}-{next_roll_no}" # 예: 2405001-1
                        new_roll_doc['parent_id'] = sel_id
                        new_roll_doc['roll_no'] = next_roll_no
                        new_roll_doc['weaving_end_time'] = end_dt
                        new_roll_doc['real_weight'] = real_weight_g
                        new_roll_doc['real_stock'] = real_stock_val
                        new_roll_doc['stock'] = real_stock_val # 중요: 이후 공정은 이 롤의 수량을 기준으로 함
                        new_roll_doc['prod_weight_kg'] = prod_weight_val
                        new_roll_doc['avg_weight'] = avg_weight_val
                        
                        # 불필요한 필드 제거
                        if 'completed_rolls' in new_roll_doc: del new_roll_doc['completed_rolls']
                        # [수정] 총 롤 수 정보를 유지하기 위해 삭제 구문 주석 처리
                        # if 'weaving_roll_count' in new_roll_doc: del new_roll_doc['weaving_roll_count']
                        
                        db.collection("orders").add(new_roll_doc)
                        
                        # 2. 부모 문서 업데이트 (진행률 표시)
                        updates = {"completed_rolls": next_roll_no}
                        
                        # 마지막 롤이면 부모 문서는 '제직완료(Master)' 상태로 변경하여 목록에서 숨김
                        if next_roll_no >= total_rolls:
                            updates["status"] = "제직완료(Master)"
                            msg = f"🎉 마지막 롤({next_roll_no}/{total_rolls})까지 처리가 완료되었습니다!"
                        else:
                            msg = f"✅ {next_roll_no}번 롤 처리가 완료되었습니다. 이어서 {next_roll_no + 1}번 롤을 입력해주세요."
                        
                        db.collection("orders").document(sel_id).update(updates)
                        
                        # 메시지를 세션에 저장하여 리런 후에도 보이게 함
                        st.session_state["weaving_msg"] = msg
                        
                        # [중요] 저장 후 선택 초기화를 위해 키 증가
                        st.session_state["weaving_df_key"] += 1
                        
                        # 세션 정리
                        if ss_stock_key in st.session_state: del st.session_state[ss_stock_key]
                        if ss_kg_key in st.session_state: del st.session_state[ss_kg_key]
                        
                        st.rerun()
                
                if st.button("🚫 제직 취소 (대기로 되돌리기)", key="cancel_weaving"):
                    db.collection("orders").document(sel_id).update({
                        "status": "제직대기",
                        "machine_no": firestore.DELETE_FIELD,
                        "weaving_start_time": firestore.DELETE_FIELD
                    })
                    st.session_state["weaving_df_key"] += 1
                    st.rerun()
        else:
            st.info("현재 제직 중인 작업이 없습니다.")

    # --- 3. 제직완료 탭 ---
    elif sub_menu == "제직완료 목록":
        st.subheader("제직 완료 목록")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (제직완료)
        if "key_weaving_done" not in st.session_state:
            st.session_state["key_weaving_done"] = 0

        # 검색 조건 (기간 + 발주처 + 제품명)
        with st.form("search_weaving_done"):
            c1, c2, c3 = st.columns([2, 1, 1])
            today = datetime.date.today()
            s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
            s_cust = c2.text_input("발주처 검색")
            s_prod = c3.text_input("제품명 검색")
            st.form_submit_button("🔍 조회")

        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)

        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        # 제직완료 이후의 모든 상태 포함
        target_statuses = ["제직완료", "제직완료(Master)", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (weaving_end_time 기준)
            w_end = d.get('weaving_end_time')
            if w_end:
                if w_end.tzinfo: w_end = w_end.replace(tzinfo=None) # 시간대 정보 제거 후 비교
                if not (start_dt <= w_end <= end_dt): continue
            else:
                continue
            
            # 2. 발주처 필터
            if s_cust and s_cust not in d.get('customer', ''):
                continue
            
            # 3. 제품명 필터
            if s_prod and s_prod not in d.get('name', ''):
                continue
                
            rows.append(d)
        
        # 최신순 정렬
        rows.sort(key=lambda x: x.get('weaving_end_time', datetime.datetime.min), reverse=True)

        if rows:
            df = pd.DataFrame(rows)
            if 'weaving_end_time' in df.columns:
                df['weaving_end_time'] = df['weaving_end_time'].apply(lambda x: x.strftime('%Y-%m-%d %H:%M') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            # [NEW] 합계 정보
            total_stock = df['real_stock'].sum() if 'real_stock' in df.columns else 0
            total_weight = df['prod_weight_kg'].sum() if 'prod_weight_kg' in df.columns else 0.0
            st.markdown(f"### 📊 합계: 생산수량 **{total_stock:,}장** / 생산중량 **{total_weight:,.1f}kg**")

            # [NEW] 롤 번호 표시 형식 변경 (예: 1/3)
            if 'roll_no' in df.columns:
                # 데이터프레임에 weaving_roll_count 컬럼이 없는 경우 대비
                if 'weaving_roll_count' not in df.columns:
                    df['weaving_roll_count'] = None
                
                def get_roll_display(row):
                    try:
                        r = row.get('roll_no')
                        t = row.get('weaving_roll_count')
                        
                        # 롤 번호가 없으면 빈 문자열
                        if pd.isna(r): return ""
                        
                        # 소수점 제거 (1.0 -> 1)
                        r_str = str(int(r))
                        
                        # 총 롤 수가 유효한 숫자이면 1/3 형식으로 반환
                        if pd.notnull(t) and t != "":
                            try:
                                t_int = int(t)
                                if t_int > 0:
                                    return f"{r_str}/{t_int}"
                            except:
                                pass
                        
                        return r_str
                    except:
                        return str(row.get('roll_no', ''))

                df['roll_display'] = df.apply(get_roll_display, axis=1)

            col_map = {
                "order_no": "발주번호", "machine_no": "제직기", "weaving_end_time": "완료시간",
                "customer": "발주처", "name": "제품명", 
                "real_stock": "생산매수", "real_weight": "중량(g)", 
                "prod_weight_kg": "생산중량(kg)", "avg_weight": "평균중량(g)",
                "roll_display": "롤번호"
            }
            display_cols = ["weaving_end_time", "machine_no", "order_no", "roll_display", "customer", "name", "real_stock", "real_weight", "prod_weight_kg", "avg_weight"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            df_display = df[final_cols].rename(columns=col_map)

            # 엑셀 및 인쇄 버튼
            c_exp1, c_exp2 = st.columns([1, 5])
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            c_exp1.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"제직완료내역_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="제직 완료 내역", key="wd_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="wd_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="wd_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="wd_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="wd_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="wd_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="wd_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="wd_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="wd_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="wd_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="wd_mr")

            # [수정] utils의 generate_report_html 함수 사용
            if c_exp2.button("🖨️ 바로 인쇄하기", key="btn_print_wd"):
                options = {
                    'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                    'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                    'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
                }
                summary_text = f"합계 - 생산수량: {total_stock:,}장 / 생산중량: {total_weight:,.1f}kg"
                print_html = generate_report_html(p_title, df_display, summary_text, options)
                st.components.v1.html(print_html, height=0, width=0)

            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(
                df_display, 
                width="stretch", 
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"df_done_{st.session_state['key_weaving_done']}"
            )

            if selection.selection.rows:
                if readonly:
                    st.info("🔒 조회 전용 모드입니다. (수정 불가)")
                else:
                    idx = selection.selection.rows[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                    
                    st.divider()
                    current_status = sel_row.get('status', '')
                    if current_status not in ["제직완료", "제직완료(Master)"]:
                        st.error(f"⛔ 현재 상태가 '**{current_status}**'이므로 이 단계에서 수정하거나 취소할 수 없습니다.")
                        st.info("다음 공정(염색 등)이 이미 진행된 경우, 해당 공정에서 작업을 취소하여 상태를 되돌린 후 시도해주세요.")
                    else:
                        st.markdown(f"### 제직 결과 수정: **{sel_row['name']} ({sel_row.get('roll_no', '?')}번 롤)**")
                        
                        with st.form("edit_weaving_done"):
                            c1, c2 = st.columns(2)
                            new_real_weight = c1.number_input("중량(g)", value=int(sel_row.get('real_weight', 0)), step=1, format="%d")
                            new_real_stock = c2.number_input("생산매수(장)", value=int(sel_row.get('real_stock', 0)), step=1, format="%d")
                            
                            c3, c4 = st.columns(2)
                            new_prod_kg = c3.number_input("생산중량(kg)", value=float(sel_row.get('prod_weight_kg', 0)), step=0.1, format="%.1f")
                            new_avg_weight = c4.number_input("평균중량(g)", value=float(sel_row.get('avg_weight', 0)), step=0.1, format="%.1f")
                            
                            if st.form_submit_button("수정 저장"):
                                db.collection("orders").document(sel_id).update({
                                    "real_weight": new_real_weight,
                                    "real_stock": new_real_stock,
                                    "stock": new_real_stock, # 이후 공정을 위해 재고 수량도 함께 업데이트
                                    "prod_weight_kg": new_prod_kg,
                                    "avg_weight": new_avg_weight
                                })
                                st.success("수정되었습니다.")
                                st.session_state["key_weaving_done"] += 1
                                st.rerun()

                        st.markdown("#### 제직 완료 취소 (삭제)")
                        st.warning("이 롤 데이터를 삭제하고, 제직중 상태로 되돌립니다.")
                        if st.button("🗑️ 이 롤 삭제하기 (취소)", type="primary"):
                            parent_id = sel_row.get('parent_id')
                            
                            # 1. 현재 롤 문서 삭제
                            db.collection("orders").document(sel_id).delete()
                            
                            # 2. 부모 문서(제직중인 건) 상태 업데이트
                            if parent_id:
                                # 남은 형제 롤 개수 확인
                                siblings = db.collection("orders").where("parent_id", "==", parent_id).where("status", "==", "제직완료").stream()
                                cnt = sum(1 for _ in siblings)
                                
                                db.collection("orders").document(parent_id).update({
                                    "completed_rolls": cnt,
                                    "status": "제직중" # 마스터 완료 상태였더라도 다시 제직중으로 복귀
                                })
                            
                            st.success("삭제되었습니다. 제직중 목록에서 다시 작업할 수 있습니다.")
                            st.session_state["key_weaving_done"] += 1
                            st.rerun()
        else:
            st.info("제직 완료된 내역이 없습니다.")

    # --- 4. 작업일지 탭 ---
    elif sub_menu == "작업일지":
        st.subheader("작업일지 작성 및 조회")
        
        # [NEW] 저장 성공 메시지 (리런 후 표시)
        if st.session_state.get("worklog_saved"):
            st.success("✅ 작업일지가 저장되었습니다.")
            st.session_state["worklog_saved"] = False

        # Part 1: 일지 작성
        with st.expander("작업일지 작성하기", expanded=True):
            # [수정] st.form 제거하여 라디오 버튼 즉시 반응하도록 변경 (라벨 동적 변경을 위해)
            if "wl_form_key" not in st.session_state:
                st.session_state["wl_form_key"] = 0

            c1, c2, c3 = st.columns(3)
            # key에 접미사를 붙여 저장 후 초기화(새로운 키=새로운 위젯) 효과 구현
            log_date = c1.date_input("작업일자", datetime.date.today(), key=f"wl_date_{st.session_state['wl_form_key']}")
            shift = c2.radio("근무조", ["주간", "야간"], horizontal=True, key=f"wl_shift_{st.session_state['wl_form_key']}")
            
            default_author = st.session_state.get("user_name", st.session_state.get("role", ""))
            author = c3.text_input("작성자", value=default_author, key=f"wl_author_{st.session_state['wl_form_key']}")

            c1, c2 = st.columns(2)
            # [수정] 제직기 다중 선택 및 기타 옵션 추가
            m_names = [m['name'] for m in machines_data]
            machine_options = ["전체"] + m_names + ["기타"]
            machine_selection = c1.multiselect("제직기", machine_options, default=[], key=f"wl_machines_{st.session_state['wl_form_key']}")
            
            log_time = c2.time_input("작성시간", datetime.datetime.now().time(), key=f"wl_time_{st.session_state['wl_form_key']}")
            
            content = st.text_area("작업 내용", key=f"wl_content_{st.session_state['wl_form_key']}")
            
            # [핵심] 근무조 선택에 따라 라벨 동적 변경 (st.form 밖이므로 즉시 반영됨)
            handover_label = "야간근무자 전달사항" if shift == "주간" else "주간근무자 전달사항"
            handover_notes = st.text_area(handover_label, help="다음 근무조에게 전달할 내용을 입력하세요.", key=f"wl_note_{st.session_state['wl_form_key']}")
            
            if st.button("일지 저장", type="primary"):
                log_dt = datetime.datetime.combine(log_date, log_time)
                
                # [수정] 선택된 제직기들을 문자열로 변환
                if not machine_selection:
                    machine_no_str = "-"
                else:
                    machine_no_str = ", ".join(machine_selection)
                
                # 1. 개별 로그 저장 (shift_logs 컬렉션)
                db.collection("shift_logs").add({
                    "log_date": str(log_date),
                    "shift": shift,
                    "machine_no": machine_no_str,
                    "log_time": log_dt,
                    "content": content,
                    "author": author
                })
                
                # 2. 전달사항 저장 (handover_notes 컬렉션)
                if handover_notes:
                    note_key = "day_to_night_notes" if shift == "주간" else "night_to_day_notes"
                    db.collection("handover_notes").document(str(log_date)).set({
                        note_key: handover_notes
                    }, merge=True)
                
                st.session_state["worklog_saved"] = True
                st.session_state["wl_form_key"] += 1 # 키 변경으로 입력 폼 초기화
                st.rerun()

        # Part 2: 일지 조회
        st.divider()
        st.subheader("일지 조회 및 출력")
        
        # [수정] 데이터가 있는 날짜 목록 가져오기
        available_dates = set()
        # 1. 작업일지 데이터 날짜
        logs_ref = db.collection("shift_logs").stream()
        for doc in logs_ref:
            if doc.to_dict().get('log_date'):
                available_dates.add(doc.to_dict().get('log_date'))
        # 2. 전달사항 데이터 날짜 (문서 ID가 날짜)
        notes_ref = db.collection("handover_notes").stream()
        for doc in notes_ref:
            available_dates.add(doc.id)
            
        sorted_dates = sorted(list(available_dates), reverse=True)
        
        c1, c2 = st.columns([1, 3])
        view_date = c1.selectbox("조회할 날짜 선택", sorted_dates if sorted_dates else [str(datetime.date.today())], key="worklog_view_date")
        
        # 데이터 가져오기
        # Firestore 복합 인덱스 오류 방지를 위해 order_by 제거 후 Python에서 정렬
        log_docs = list(db.collection("shift_logs").where("log_date", "==", str(view_date)).stream())
        log_docs.sort(key=lambda x: x.to_dict().get('log_time', datetime.datetime.min))
        notes_doc = db.collection("handover_notes").document(str(view_date)).get()
        
        day_logs = []
        night_logs = []
        for doc in log_docs:
            log_data = doc.to_dict()
            if log_data['shift'] == '주간':
                day_logs.append(log_data)
            else:
                night_logs.append(log_data)
        
        notes_data = notes_doc.to_dict() if notes_doc.exists else {}
        
        # 인쇄 옵션 설정
        with st.expander("🖨️ 인쇄 옵션 설정"):
            po_c1, po_c2, po_c3, po_c4 = st.columns(4)
            p_title = po_c1.text_input("제목", value="작업 일지", key="wl_title")
            p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="wl_ts")
            p_body_size = po_c3.number_input("본문 글자 크기(px)", value=12, step=1, key="wl_bs")
            p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="wl_pad")
            
            po_c5, po_c6, po_c7 = st.columns(3)
            p_show_date = po_c5.checkbox("출력일시 표시 (좌측상단)", value=True, key="wl_sd")
            p_show_work_date = po_c6.checkbox("작성일자 표시 (우측상단)", value=True, key="wl_swd")
            p_date_size = po_c7.number_input("일자 글자 크기(px)", value=12, step=1, key="wl_ds")
            
            st.caption("페이지 여백 (mm)")
            po_c8, po_c9, po_c10, po_c11 = st.columns(4)
            p_m_top = po_c8.number_input("상단", value=15, step=1, key="wl_mt")
            p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="wl_mb")
            p_m_left = po_c10.number_input("좌측", value=15, step=1, key="wl_ml")
            p_m_right = po_c11.number_input("우측", value=15, step=1, key="wl_mr")

        # 화면 표시 & 인쇄용 HTML 생성
        print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        print_date_display = "block" if p_show_date else "none"
        work_date_display = "block" if p_show_work_date else "none"

        style = f"""<style>
            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: {p_body_size}px; }}
            th, td {{ border: 1px solid #444; padding: {p_padding}px; text-align: left; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: {p_body_size}px; table-layout: fixed; }}
            th, td {{ border: 1px solid #444; padding: {p_padding}px; text-align: left; word-wrap: break-word; }}
            th {{ background-color: #f0f0f0; text-align: center; font-weight: bold; }}
            
            /* [수정] 컬럼 너비 조정 */
            th:nth-child(1), td:nth-child(1) {{ width: 10%; text-align: center; }} /* 시간 */
            th:nth-child(2), td:nth-child(2) {{ width: 15%; text-align: center; }} /* 제직기 */
            th:nth-child(3), td:nth-child(3) {{ width: 65%; }} /* 내용 */
            th:nth-child(4), td:nth-child(4) {{ width: 10%; text-align: center; }} /* 작성자 */
            
            .print-date {{ text-align: left; font-size: 10px; color: #555; margin-bottom: 5px; display: {print_date_display}; }}
            .header {{ text-align: center; margin-bottom: 5px; }}
            .header h2 {{ font-size: {p_title_size}px; margin: 0; }}
            .work-date {{ text-align: right; font-size: {p_date_size}px; font-weight: bold; margin-bottom: 10px; display: {work_date_display}; }}
            
            .section-title {{ font-size: {p_body_size + 2}px; font-weight: bold; margin-top: 20px; margin-bottom: 5px; border-bottom: 2px solid #ddd; padding-bottom: 3px; }}
            .note-box {{ border: 1px solid #444; padding: 10px; min-height: 60px; font-size: {p_body_size}px; }}
        </style>"""
        
        html_content = f"<html><head><title>{p_title}</title>{style}</head><body>"
        html_content += f"<div class='print-date'>출력일시: {print_now}</div>"
        html_content += f"<div class='header'><h2>{p_title}</h2></div>"
        html_content += f"<div class='work-date'>작성일자: {view_date}</div>"
        
        # 주간 섹션
        st.markdown("#### ☀️ 주간 작업")
        html_content += "<div class='section-title'>☀️ 주간 작업</div>"
        st.markdown("#### 주간 작업")
        html_content += "<div class='section-title'>주간 작업</div>"
        if day_logs:
            df_day = pd.DataFrame(day_logs)
            df_day['log_time'] = df_day['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
            # [수정] 컬럼명 변경 (호기 -> 제직기)
            st.dataframe(
                df_day[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'제직기','content':'내용','author':'작성자'}), 
                hide_index=True, 
                use_container_width=True,
                column_config={"시간": st.column_config.TextColumn(width=60), "제직기": st.column_config.TextColumn(width=80), "내용": st.column_config.TextColumn(width="large"), "작성자": st.column_config.TextColumn(width=80)}
            )
            html_content += df_day[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'제직기','content':'내용','author':'작성자'}).to_html(index=False, border=1)
        else:
            st.info("기록 없음")
            html_content += "<p>기록 없음</p>"
            st.info("작성내역 없음")
            html_content += "<p>작성내역 없음</p>"
            
        st.markdown("##### 📝 야간근무자 전달사항")
        d_note = notes_data.get('day_to_night_notes', '-')
        st.warning(d_note)
        html_content += f"<div class='section-title'>📝 야간근무자 전달사항</div><div class='note-box'>{d_note}</div>"

        st.divider()

        # 야간 섹션
        st.markdown("#### 🌙 야간 작업")
        st.markdown("#### 야간 작업")
        html_content += "<div class='section-title'>🌙 야간 작업</div>"
        if night_logs:
            df_night = pd.DataFrame(night_logs)
            df_night['log_time'] = df_night['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
            # [수정] 컬럼명 변경 (호기 -> 제직기)
            st.dataframe(
                df_night[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'제직기','content':'내용','author':'작성자'}), 
                hide_index=True, 
                use_container_width=True,
                column_config={"시간": st.column_config.TextColumn(width=60), "제직기": st.column_config.TextColumn(width=80), "내용": st.column_config.TextColumn(width="large"), "작성자": st.column_config.TextColumn(width=80)}
            )
            html_content += df_night[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'제직기','content':'내용','author':'작성자'}).to_html(index=False, border=1)
        else:
            st.info("기록 없음")
            html_content += "<p>기록 없음</p>"
            st.info("작성내역 없음")
            html_content += "<p>작성내역 없음</p>"

        st.markdown("##### 📝 주간근무자 전달사항")
        n_note = notes_data.get('night_to_day_notes', '-')
        st.warning(n_note)
        html_content += f"<div class='section-title'>📝 주간근무자 전달사항</div><div class='note-box'>{n_note}</div>"
        html_content += "</body></html>"
        
        # [수정] '바로 인쇄하기' 로직으로 변경
        with c2:
            if st.button("🖨️ 작업일지 바로 인쇄하기"):
                final_print_html = html_content.replace(
                    "</head>",
                    """<style> @media screen { body { display: none; } } </style></head>"""
                ).replace(
                    "<body>",
                    '<body onload="window.print();">'
                )
                st.components.v1.html(final_print_html, height=0, width=0)

    # --- 5. 생산일지 탭 ---
    elif sub_menu == "생산일지":
        st.subheader("일일 생산일지 조회")
        
        # [수정] 생산 실적이 있는 날짜 목록 가져오기
        # 제직완료 이상 상태인 건들의 weaving_end_time 확인
        target_statuses = ["제직완료", "제직완료(Master)", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
        inv_ref = db.collection("orders").where("status", "in", target_statuses).stream()
        prod_dates = set()
        for doc in inv_ref:
            d = doc.to_dict()
            w_end = d.get('weaving_end_time')
            if w_end:
                if isinstance(w_end, datetime.datetime):
                    prod_dates.add(w_end.strftime("%Y-%m-%d"))
                elif isinstance(w_end, str):
                    prod_dates.add(w_end[:10])
        
        sorted_prod_dates = sorted(list(prod_dates), reverse=True)
        
        c1, c2 = st.columns([1, 3])
        prod_date_str = c1.selectbox("조회일자 선택", sorted_prod_dates if sorted_prod_dates else [str(datetime.date.today())], key="prodlog_view_date")
        prod_date = datetime.datetime.strptime(prod_date_str, "%Y-%m-%d").date()
        
        start_dt = datetime.datetime.combine(prod_date, datetime.time.min)
        end_dt = datetime.datetime.combine(prod_date, datetime.time.max)
        
        # Firestore 인덱스 오류 방지를 위해 status만 쿼리하고 날짜는 파이썬에서 필터링
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            w_end = d.get('weaving_end_time')
            if w_end:
                if w_end.tzinfo: w_end = w_end.replace(tzinfo=None)
                if start_dt <= w_end <= end_dt:
                    rows.append(d)
        
        if rows:
            df = pd.DataFrame(rows)
            df['weaving_end_time'] = df['weaving_end_time'].apply(lambda x: x.strftime('%H:%M') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            col_map = {"order_no": "발주번호", "machine_no": "제직기", "weaving_end_time": "완료시간", "customer": "발주처", "name": "제품명", "real_stock": "생산매수", "real_weight": "중량(g)", "prod_weight_kg": "생산중량(kg)", "avg_weight": "평균중량(g)", "roll_no": "롤번호"}
            display_cols = ["weaving_end_time", "machine_no", "order_no", "roll_no", "customer", "name", "real_stock", "real_weight", "prod_weight_kg", "avg_weight"]
            final_cols = [c for c in display_cols if c in df.columns]
            df_display = df[final_cols].rename(columns=col_map)
            st.markdown(f"### 📄 {prod_date} 생산일지")
            st.markdown(f"### {prod_date} 생산일지")
            st.dataframe(df_display, hide_index=True, width="stretch")
            
            # 엑셀 다운로드 준비
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value=f"{prod_date} 생산일지", key="pl_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="pl_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="pl_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="pl_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="pl_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="pl_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="pl_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="pl_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="pl_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="pl_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="pl_mr")

            # [수정] utils의 generate_report_html 함수 사용
            options = {
                'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
            }
            print_html = generate_report_html(p_title, df_display, "", options)
            print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            date_align = p_date_pos.lower()
            date_display = "block" if p_show_date else "none"

            print_html = f"""<html><head><title>{p_title}</title>
            <style>
                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
                @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                .info {{ text-align: {date_align}; font-size: {p_date_size}px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; }}
                th, td {{ border: 1px solid #444; padding: {p_padding}px 4px; text-align: center; }}
                th {{ background-color: #f0f0f0; }}
            </style></head><body>
            <h2>{p_title}</h2>
            <div class="info">출력일시: {print_now}</div>
            {df_display.to_html(index=False)}</body></html>"""
            
            with c2:
                c2_1, c2_2 = st.columns(2)
                
                # [수정] '바로 인쇄하기' 로직으로 변경
                if c2_1.button("🖨️ 바로 인쇄하기"):
                    final_print_html = print_html.replace(
                        "</head>",
                        """<style> @media screen { body { display: none; } } </style></head>"""
                    ).replace(
                        "<body>",
                        '<body onload="window.print();">'
                    )
                    st.components.v1.html(final_print_html, height=0, width=0)

                c2_2.download_button(
                    label="💾 엑셀 다운로드",
                    data=buffer.getvalue(),
                    file_name=f"생산일지_{prod_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info(f"{prod_date}에 완료된 생산 내역이 없습니다.")

def render_dyeing(db, sub_menu):
    st.header("염색 현황")
    st.info("제직이 완료된 건을 염색 공장에서 작업하고 봉제 단계로 넘깁니다.")

    # 염색 업체 목록 가져오기
    dyeing_partners = get_partners("염색업체")

    # [NEW] 색번 기초 코드 가져오기
    color_codes = get_common_codes("color_codes", [])
    # [수정] 색번(색상) 형식으로 표시 (예: W0041 (신백색)) - 순서 재확인
    color_opts = ["선택하세요"] + [f"{c['code']} ({c['name']})" for c in color_codes] if color_codes else ["선택하세요"]

    # --- 1. 염색 대기 탭 ---
    if sub_menu == "염색 대기 목록":
        st.subheader("염색 대기 목록 (제직완료)")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (염색대기)
        if "key_dyeing_wait" not in st.session_state:
            st.session_state["key_dyeing_wait"] = 0
            
        # [수정] 안내 문구 삭제 요청 반영
        # st.info("💡 색번(Color Code)은 상단의 **[🎨 색번 설정]** 탭에서 등록할 수 있습니다.")
        docs = db.collection("orders").where("status", "==", "제직완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        
        # 날짜순 정렬
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))

        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                "color": "색상", "stock": "수량", "weight": "중량(g)", 
                "prod_weight_kg": "제직중량(kg)", "roll_no": "롤번호", "date": "접수일"
            }
            display_cols = ["order_no", "roll_no", "customer", "name", "color", "stock", "weight", "prod_weight_kg", "date"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 염색 출고할 항목을 선택하세요. (다중 선택 가능)")
            # [수정] 다중 선택 모드로 변경
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="multi-row", key=f"df_dye_wait_{st.session_state['key_dyeing_wait']}")
            
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]

                # [NEW] 다중 선택 시: 염색 작업 지시서 출력 (현장용)
                with st.expander("염색 작업 지시서 출력 (현장 확인용)", expanded=False):
                    st.info("선택한 항목에 대해 **염색업체**와 **솥번호**를 지정하여 작업 지시서를 출력합니다. (이 정보는 DB에 저장되지 않습니다)")
                    
                    # 데이터 에디터용 데이터프레임 생성
                    edit_df = selected_rows.copy()
                    # 기본값 설정
                    edit_df['염색업체'] = "" 
                    edit_df['솥번호'] = "1"
                    edit_df['비고'] = ""
                    
                    # 표시할 컬럼 정리
                    edit_view = edit_df[['name', 'color', 'prod_weight_kg', 'stock', '염색업체', '솥번호', '비고']].rename(columns={
                        'name': '제품명', 'color': '색상', 'prod_weight_kg': '중량(kg)', 'stock': '수량'
                    })
                    
                    # 데이터 에디터 (업체, 솥번호 입력)
                    edited_data = st.data_editor(
                        edit_view,
                        column_config={
                            "제품명": st.column_config.TextColumn(disabled=True),
                            "색상": st.column_config.TextColumn(disabled=True),
                            "중량(kg)": st.column_config.NumberColumn(disabled=True, format="%.1f"),
                            "수량": st.column_config.NumberColumn(disabled=True),
                            "염색업체": st.column_config.SelectboxColumn("염색업체", options=dyeing_partners, required=True),
                            "솥번호": st.column_config.TextColumn("솥번호", help="같은 업체 내에서 솥번호별로 그룹화됩니다."),
                            "비고": st.column_config.TextColumn("비고")
                        },
                        hide_index=True,
                        use_container_width=True,
                        key="dye_print_editor"
                    )
                    
                    # [NEW] 인쇄 옵션 설정
                    with st.expander("🖨️ 인쇄 옵션 설정"):
                        po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                        p_title = po_c1.text_input("제목", value="염색 작업 지시서", key="dye_p_title")
                        p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="dye_p_ts")
                        p_body_size = po_c3.number_input("본문 글자 크기(px)", value=12, step=1, key="dye_p_bs")
                        p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="dye_p_pad")
                        
                        st.caption("페이지 여백 (mm)")
                        po_c5, po_c6, po_c7, po_c8 = st.columns(4)
                        p_m_top = po_c5.number_input("상단", value=15, step=1, key="dye_p_mt")
                        p_m_bottom = po_c6.number_input("하단", value=15, step=1, key="dye_p_mb")
                        p_m_left = po_c7.number_input("좌측", value=15, step=1, key="dye_p_ml")
                        p_m_right = po_c8.number_input("우측", value=15, step=1, key="dye_p_mr")

                    if st.button("🖨️ 작업 지시서 인쇄"):
                        # 그룹화 및 HTML 생성 로직
                        print_html = f"""
                        <html>
                        <head>
                            <title>{p_title}</title>
                            <style>
                                @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                                h2 {{ text-align: center; border-bottom: 2px solid #333; padding-bottom: 10px; font-size: {p_title_size}px; margin-top: 0; }}
                                .partner-section {{ margin-bottom: 30px; border: 1px solid #999; padding: 15px; page-break-inside: avoid; }}
                                .partner-title {{ font-size: {p_body_size + 6}px; font-weight: bold; background-color: #eee; padding: 5px; margin-bottom: 10px; }}
                                .pot-section {{ margin-left: 10px; margin-bottom: 15px; }}
                                .pot-title {{ font-size: {p_body_size + 4}px; font-weight: bold; color: #0066cc; margin-bottom: 5px; border-bottom: 1px solid #ddd; }}
                                table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; margin-bottom: 5px; }}
                                th, td {{ border: 1px solid #ccc; padding: {p_padding}px; text-align: center; }}
                                th {{ background-color: #f8f9fa; }}
                                .total-row {{ font-weight: bold; background-color: #fffbe6; }}
                                @media screen {{ body {{ display: none; }} }}
                            </style>
                        </head>
                        <body onload="window.print()">
                            <h2>{p_title}</h2>
                            <div style="text-align: right; font-size: 10px; margin-bottom: 10px;">출력일시: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
                        """
                        
                        # 그룹화: 염색업체 -> 솥번호
                        if not edited_data.empty:
                            # 업체가 없는 경우 '미지정' 처리
                            edited_data['염색업체'] = edited_data['염색업체'].fillna('미지정').replace('', '미지정')
                            
                            for partner, p_group in edited_data.groupby('염색업체'):
                                print_html += f"<div class='partner-section'><div class='partner-title'>🏭 업체: {partner}</div>"
                                
                                for pot, pot_group in p_group.groupby('솥번호'):
                                    # 솥 합계 계산
                                    sum_weight = pot_group['중량(kg)'].sum()
                                    sum_qty = pot_group['수량'].sum()
                                    
                                    print_html += f"<div class='pot-section'><div class='pot-title'>🔹 솥번호: {pot}</div>"
                                    print_html += pot_group.to_html(index=False, classes='table', border=0)
                                    print_html += f"<div style='text-align:right; font-weight:bold; margin-top:5px;'>[합계] 수량: {sum_qty:,}장 / 중량: {sum_weight:,.1f}kg</div></div>"
                                
                                print_html += "</div>"
                        
                        print_html += "</body></html>"
                        st.components.v1.html(print_html, height=0, width=0)

                # [기존] 개별 출고 처리 (단일 선택 시에만 표시)
                if len(selected_indices) == 1:
                    idx = selected_indices[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                
                    st.divider()
                    st.markdown(f"### 염색 출고 정보 입력: **{sel_row['name']}**")
                    
                    with st.form("dyeing_start_form"):
                        c1, c2 = st.columns(2)
                        d_date = c1.date_input("염색출고일", datetime.date.today())
                        d_partner = c2.selectbox("염색업체", dyeing_partners if dyeing_partners else ["직접입력"])
                        
                        c3, c4 = st.columns(2)
                        # [NEW] 색번 선택 콤보박스 추가
                        d_color_code_sel = c3.selectbox("색번 선택", color_opts)
                        
                        # 기본값으로 제직 생산 중량 사용
                        def_weight = float(sel_row.get('prod_weight_kg', 0))
                        d_weight = c4.number_input("출고중량(kg)", value=def_weight, step=0.1, format="%.1f")
                        
                        d_note = st.text_input("염색사항(비고)")
                        
                        if st.form_submit_button("염색 출고 (작업시작)"):
                            # 색번 파싱
                            sel_cc, sel_cn = "", ""
                            if d_color_code_sel != "선택하세요":
                                try:
                                    sel_cc, rest = d_color_code_sel.split(" (", 1)
                                    sel_cn = rest[:-1]
                                except:
                                    sel_cc = d_color_code_sel

                            db.collection("orders").document(sel_id).update({
                                "status": "염색중",
                                "dyeing_out_date": str(d_date),
                                "dyeing_partner": d_partner,
                                "dyeing_out_weight": d_weight,
                                "dyeing_note": d_note,
                                "dyeing_color_code": sel_cc,
                                "dyeing_color_name": sel_cn
                            })
                            st.success("염색중 상태로 변경되었습니다.")
                            st.session_state["key_dyeing_wait"] += 1 # 목록 선택 초기화
                            st.rerun()
        else:
            st.info("염색 대기 중인 건이 없습니다.")

    # --- 2. 염색중 탭 ---
    elif sub_menu == "염색중 목록":
        st.subheader("염색중 목록")
        
        if "key_dyeing_ing" not in st.session_state:
            st.session_state["key_dyeing_ing"] = 0
            
        docs = db.collection("orders").where("status", "==", "염색중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            # 비고 컬럼이 없는 경우 빈 값으로 초기화 (데이터가 없을 때 오류 방지)
            if 'dyeing_note' not in df.columns:
                df['dyeing_note'] = ""

            col_map = {
                "order_no": "발주번호", "dyeing_partner": "염색업체", "dyeing_out_date": "출고일",
                "name": "제품명", "color": "색상", "dyeing_color_code": "색번", "stock": "수량", "dyeing_out_weight": "출고중량(kg)",
                "roll_no": "롤번호", "dyeing_note": "비고"
            }
            display_cols = ["dyeing_out_date", "dyeing_partner", "order_no", "roll_no", "name", "color", "dyeing_color_code", "stock", "dyeing_out_weight", "dyeing_note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 관리할 항목을 선택하세요.")
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_dye_ing_{st.session_state['key_dyeing_ing']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 작업 관리: **{sel_row['name']}**")
                
                tab_act1, tab_act2 = st.tabs(["염색 완료 처리", "정보 수정 / 취소"])
                
                with tab_act1:
                    st.write("염색 완료(입고) 정보를 입력하세요.")
                    c1, c2 = st.columns(2)
                    d_in_date = c1.date_input("염색완료일(입고일)", datetime.date.today())
                    d_stock = c2.number_input("입고수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                    
                    c3, c4 = st.columns(2)
                    # 기본값으로 출고 중량 사용
                    def_weight = float(sel_row.get('dyeing_out_weight', 0)) if not pd.isna(sel_row.get('dyeing_out_weight')) else 0.0
                    d_weight = c3.number_input("입고중량(kg)", value=def_weight, step=0.1, format="%.1f")
                    d_price = c4.number_input("염색단가(원)", min_value=0, step=1)
                    
                    d_vat_inc = st.checkbox("부가세 포함", value=False, key="dye_vat_check")
                    
                    base_calc = int(d_weight * d_price)
                    if d_vat_inc:
                        d_supply = int(base_calc / 1.1)
                        d_vat = base_calc - d_supply
                        d_total = base_calc
                    else:
                        d_supply = base_calc
                        d_vat = int(base_calc * 0.1)
                        d_total = base_calc + d_vat
                    
                    st.info(f"💰 **염색비용 합계**: {d_total:,}원 (공급가: {d_supply:,}원 / 부가세: {d_vat:,}원)")
                    
                    if st.button("염색 완료 (봉제대기로 이동)"):
                        db.collection("orders").document(sel_id).update({
                            "status": "염색완료",
                            "dyeing_in_date": str(d_in_date),
                            "stock": d_stock,
                            "dyeing_in_weight": d_weight,
                            "dyeing_unit_price": d_price,
                            "dyeing_amount": d_total,
                            "dyeing_supply": d_supply,
                            "dyeing_vat": d_vat,
                            "vat_included": d_vat_inc
                        })
                        st.success(f"염색이 완료되었습니다. (합계: {d_total:,}원)")
                        st.session_state["key_dyeing_ing"] += 1
                        st.rerun()
                            
                with tab_act2:
                    with st.form("dyeing_edit_form"):
                        st.write("출고 정보를 수정합니다.")
                        st.caption("💡 색번 목록이 보이지 않으면 **[🎨 색번 설정]** 탭에서 먼저 등록하세요.")
                        c1, c2 = st.columns(2)
                        e_date = c1.date_input("염색출고일", datetime.datetime.strptime(sel_row['dyeing_out_date'], "%Y-%m-%d").date() if sel_row.get('dyeing_out_date') else datetime.date.today())
                        e_partner = c2.selectbox("염색업체", dyeing_partners if dyeing_partners else ["직접입력"], index=dyeing_partners.index(sel_row['dyeing_partner']) if sel_row.get('dyeing_partner') in dyeing_partners else 0)
                        
                        c3, c4 = st.columns(2)
                        # [NEW] 색번 수정
                        curr_cc = sel_row.get('dyeing_color_code', '')
                        curr_cn = sel_row.get('dyeing_color_name', '')
                        # [수정] 색번(색상) 형식 유지
                        curr_val = f"{curr_cc} ({curr_cn})" if curr_cc and curr_cn else "선택하세요"
                        # 옵션에 없으면 추가 (기존 데이터 보존)
                        if curr_val not in color_opts and curr_val != "선택하세요":
                             color_opts.append(curr_val)
                        
                        e_color_sel = c3.selectbox("색번", color_opts, index=color_opts.index(curr_val) if curr_val in color_opts else 0)
                        e_weight = c4.number_input("출고중량(kg)", value=float(sel_row.get('dyeing_out_weight', 0)), step=0.1, format="%.1f")
                        
                        e_note = st.text_input("염색사항", value=sel_row.get('dyeing_note', ''))
                        
                        if st.form_submit_button("수정 저장"):
                            e_cc, e_cn = "", ""
                            if e_color_sel != "선택하세요":
                                try: e_cc, rest = e_color_sel.split(" (", 1); e_cn = rest[:-1]
                                except: e_cc = e_color_sel

                            db.collection("orders").document(sel_id).update({
                                "dyeing_out_date": str(e_date),
                                "dyeing_partner": e_partner,
                                "dyeing_out_weight": e_weight,
                                "dyeing_note": e_note,
                                "dyeing_color_code": e_cc,
                                "dyeing_color_name": e_cn
                            })
                            st.success("수정되었습니다.")
                            st.session_state["key_dyeing_ing"] += 1
                            st.rerun()
                    
                    st.markdown("#### 작업 취소")
                    if st.button("염색 취소 (대기로 되돌리기)", type="primary"):
                        db.collection("orders").document(sel_id).update({
                            "status": "제직완료"
                        })
                        st.success("취소되었습니다.")
                        st.session_state["key_dyeing_ing"] += 1
                        st.rerun()
        else:
            st.info("현재 염색 중인 작업이 없습니다.")

    # --- 3. 염색 완료 탭 ---
    elif sub_menu == "염색 완료 목록":
        st.subheader("염색 완료 목록")
        
        if "key_dyeing_done" not in st.session_state:
            st.session_state["key_dyeing_done"] = 0
        
        # 검색 조건 (기간 + 염색업체 + 발주처)
        with st.form("search_dye_done"):
            c1, c2, c3 = st.columns([2, 1, 1])
            today = datetime.date.today()
            s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
            s_partner = c2.text_input("염색업체")
            s_customer = c3.text_input("발주처")
            st.form_submit_button("🔍 조회")

        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)

        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        target_statuses = ["염색완료", "봉제중", "봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 1. 날짜 필터 (dyeing_in_date 기준)
            d_date_str = d.get('dyeing_in_date')
            if d_date_str:
                try:
                    d_date_obj = datetime.datetime.strptime(d_date_str, "%Y-%m-%d")
                    if not (start_dt <= d_date_obj <= end_dt): continue
                except:
                    continue
            else:
                continue
            
            # 2. 염색업체 필터
            if s_partner and s_partner not in d.get('dyeing_partner', ''):
                continue

            # 3. 발주처 필터
            if s_customer and s_customer not in d.get('customer', ''):
                continue
                
            rows.append(d)
            
        # 최신순 정렬 (완료일 기준)
        rows.sort(key=lambda x: x.get('dyeing_in_date', ''), reverse=True)

        if rows:
            df = pd.DataFrame(rows)
            
            # 합계 계산
            total_stock = df['stock'].sum() if 'stock' in df.columns else 0
            total_weight = df['dyeing_in_weight'].sum() if 'dyeing_in_weight' in df.columns else 0.0
            total_amount = df['dyeing_amount'].sum() if 'dyeing_amount' in df.columns else 0
            
            st.markdown(f"### 📊 합계: 수량 **{total_stock:,}장** / 중량 **{total_weight:,.1f}kg** / 금액 **{total_amount:,}원**")
            
            col_map = {
                "order_no": "발주번호", "dyeing_partner": "염색업체", "dyeing_in_date": "완료일",
                "name": "제품명", "color": "색상", "dyeing_color_code": "색번", "stock": "수량", "roll_no": "롤번호",
                "dyeing_in_weight": "입고중량(kg)", "dyeing_unit_price": "단가", "dyeing_amount": "금액",
                "customer": "발주처"
            }
            display_cols = ["dyeing_in_date", "dyeing_partner", "customer", "order_no", "roll_no", "name", "color", "dyeing_color_code", "stock", "dyeing_in_weight", "dyeing_unit_price", "dyeing_amount"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            df_display = df[final_cols].rename(columns=col_map)
            
            # 엑셀 및 인쇄 버튼
            c_exp1, c_exp2 = st.columns([1, 5])
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            c_exp1.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"염색완료내역_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="염색 완료 내역", key="dd_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="dd_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="dd_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="dd_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="dd_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="dd_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="dd_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="dd_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="dd_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="dd_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="dd_mr")

            # [수정] utils의 generate_report_html 함수 사용 (오류 원천 차단)
            if c_exp2.button("🖨️ 바로 인쇄하기", key="btn_print_dd"):
                options = {
                    'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                    'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                    'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
                }
                summary_text = f"합계 - 수량: {total_stock:,}장 / 중량: {total_weight:,.1f}kg / 금액: {total_amount:,}원"
                print_html = generate_report_html(p_title, df_display, summary_text, options)
                st.components.v1.html(print_html, height=0, width=0)

            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(df_display, width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_dye_done_{st.session_state['key_dyeing_done']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                current_status = sel_row.get('status', '')
                if current_status != "염색완료":
                    st.error(f"⛔ 현재 상태가 '**{current_status}**'이므로 이 단계에서 수정하거나 취소할 수 없습니다.")
                    st.info("다음 공정(봉제)이 이미 진행된 경우, 해당 공정에서 작업을 취소하여 상태를 되돌린 후 시도해주세요.")
                else:
                    st.markdown(f"### 완료 정보 수정: **{sel_row['name']}**")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        with st.form("dyeing_done_edit"):
                            st.write("입고 정보 수정")
                            new_in_date = st.date_input("염색완료일", datetime.datetime.strptime(sel_row['dyeing_in_date'], "%Y-%m-%d").date() if sel_row.get('dyeing_in_date') else datetime.date.today())
                            
                            c_e1, c_e2 = st.columns(2)
                            new_stock = c_e1.number_input("입고수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                            new_weight = c_e2.number_input("입고중량(kg)", value=float(sel_row.get('dyeing_in_weight', 0)) if not pd.isna(sel_row.get('dyeing_in_weight')) else 0.0, step=0.1, format="%.1f")
                            
                            c_e3, c_e4 = st.columns(2)
                            new_price = c_e3.number_input("단가(원)", value=int(sel_row.get('dyeing_unit_price', 0)) if not pd.isna(sel_row.get('dyeing_unit_price')) else 0, step=1)
                            
                            if st.form_submit_button("수정 저장"):
                                # 부가세 로직은 복잡하므로 여기서는 단순 계산만 반영
                                new_amount = int(new_weight * new_price)
                                db.collection("orders").document(sel_id).update({
                                    "dyeing_in_date": str(new_in_date),
                                    "stock": new_stock,
                                    "dyeing_in_weight": new_weight,
                                    "dyeing_unit_price": new_price,
                                    "dyeing_amount": new_amount
                                })
                                st.success("수정되었습니다.")
                                st.session_state["key_dyeing_done"] += 1
                                st.rerun()
                    with c2:
                        st.write("**완료 취소**")
                        st.warning("상태를 다시 '염색중'으로 되돌립니다.")
                        if st.button("완료 취소 (염색중으로 복귀)", type="primary"):
                            db.collection("orders").document(sel_id).update({
                                "status": "염색중"
                            })
                            st.success("복귀되었습니다.")
                            st.session_state["key_dyeing_done"] += 1
                            st.rerun()
        else:
            st.info("염색 완료된 내역이 없습니다.")

    # --- 4. 색번 설정 탭 ---
    elif sub_menu == "색번 설정":
        st.subheader("색번 관리")
        st.info("염색 출고 시 사용할 색번과 색상명을 관리합니다. (예: 명칭 '신백색' / 코드 'W0041')")
        manage_code_with_code("color_codes", [], "색번")

def render_sewing(db, sub_menu):
    st.header("봉제 현황")
    st.info("염색이 완료된 원단을 봉제하여 완제품으로 만듭니다.")
    
    sewing_partners = get_partners("봉제업체")
    
    # --- 1. 봉제 대기 탭 ---
    if sub_menu == "봉제 대기 목록":
        st.subheader("봉제 대기 목록 (염색완료)")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (봉제대기)
        if "key_sewing_wait" not in st.session_state:
            st.session_state["key_sewing_wait"] = 0
            
        docs = db.collection("orders").where("status", "==", "염색완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        
        # 날짜순 정렬
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)
            
            col_map = {
                "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                "color": "색상", "stock": "수량(장)", "dyeing_partner": "염색처", "date": "접수일", "note": "비고"
            }
            display_cols = ["order_no", "customer", "name", "color", "stock", "dyeing_partner", "date", "note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            # [NEW] 인쇄 옵션 설정 (봉제작업지시서)
            with st.expander("봉제작업지시서 인쇄 옵션"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="봉제 작업 지시서", key="si_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="si_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=12, step=1, key="si_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=10, step=1, key="si_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="si_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="si_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="si_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="si_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="si_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="si_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="si_mr")

            # [수정] 버튼을 테이블 우측 상단으로 이동
            c_head, c_btn = st.columns([0.85, 0.15])
            with c_head:
                st.write("🔽 봉제 작업할 항목을 선택하세요. (다중 선택 가능)")
            with c_btn:
                btn_print_inst = st.button("🖨️ 봉제작업지시서", use_container_width=True)

            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="multi-row", key=f"df_sew_wait_{st.session_state['key_sewing_wait']}")
            
            # [수정] 인쇄 로직 분리
            if btn_print_inst:
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    selected_rows = df.iloc[selected_indices]
                    
                    # 인쇄용 데이터 준비
                    print_df = selected_rows.copy()
                    # 참고사항 컬럼 추가 (빈 칸)
                    print_df['참고사항'] = " " * 30 
                    
                    # 인쇄할 컬럼 매핑
                    p_cols_map = {
                        "order_no": "발주번호", "customer": "발주처", "name": "제품명", 
                        "color": "색상", "stock": "수량", "note": "비고", "참고사항": "참고사항"
                    }
                    # note 컬럼이 없으면 생성
                    if 'note' not in print_df.columns: print_df['note'] = ""
                    
                    p_cols = ["order_no", "customer", "name", "color", "stock", "note", "참고사항"]
                    p_final_cols = [c for c in p_cols if c in print_df.columns]
                    
                    df_print_view = print_df[p_final_cols].rename(columns=p_cols_map)
                    
                    # 인쇄 옵션
                    options = {
                        'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                        'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                        'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
                    }
                    html = generate_report_html(p_title, df_print_view, f"총 {len(print_df)}건", options)
                    st.components.v1.html(html, height=0, width=0)
                else:
                    st.warning("출력할 항목을 선택해주세요.")

            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]

                # [기존] 봉제 시작 (단일 선택 시에만 표시)
                if len(selected_indices) == 1:
                    idx = selected_indices[0]
                    sel_row = df.iloc[idx]
                    sel_id = sel_row['id']
                    current_stock = int(sel_row.get('stock', 0))
                    
                    st.divider()
                    st.markdown(f"### 봉제 작업 시작: **{sel_row['name']}**")
                    
                    # st.form 제거 (라디오 버튼 즉시 반응을 위해)
                    c1, c2 = st.columns(2)
                    s_date = c1.date_input("봉제시작일", datetime.date.today())
                    s_type = c2.radio("작업 구분", ["자체봉제", "외주봉제"], horizontal=True, key=f"s_type_{sel_id}")
                    
                    c3, c4 = st.columns(2)
                    s_partner = c3.selectbox("봉제업체", sewing_partners if sewing_partners else ["직접입력"], disabled=(s_type=="자체봉제"), key=f"s_partner_{sel_id}")
                    s_qty = c4.number_input("작업 수량(장)", min_value=1, max_value=current_stock, value=current_stock, step=10, help="일부 수량만 작업하려면 숫자를 줄이세요.", key=f"s_qty_{sel_id}")
                    
                    if st.button("봉제 시작", key=f"btn_start_sew_{sel_id}"):
                        # 수량 분할 로직
                        if s_qty < current_stock:
                            # 1. 분할된 새 문서 생성 (작업분)
                            doc_snapshot = db.collection("orders").document(sel_id).get()
                            new_doc_data = doc_snapshot.to_dict().copy()
                            new_doc_data['stock'] = s_qty
                            new_doc_data['status'] = "봉제중"
                            new_doc_data['sewing_type'] = s_type
                            new_doc_data['sewing_start_date'] = str(s_date)
                            if s_type == "외주봉제":
                                new_doc_data['sewing_partner'] = s_partner
                            else:
                                new_doc_data['sewing_partner'] = "자체"
                            
                            db.collection("orders").add(new_doc_data)
                            
                            # 2. 원본 문서 업데이트 (잔여분)
                            db.collection("orders").document(sel_id).update({
                                "stock": current_stock - s_qty
                            })
                            st.success(f"{s_qty}장 분할하여 봉제 작업을 시작합니다. (잔여: {current_stock - s_qty}장)")
                        else:
                            # 전체 작업
                            updates = {
                                "status": "봉제중",
                                "sewing_type": s_type,
                                "sewing_start_date": str(s_date)
                            }
                            if s_type == "외주봉제":
                                updates['sewing_partner'] = s_partner
                            else:
                                updates['sewing_partner'] = "자체"
                                
                            db.collection("orders").document(sel_id).update(updates)
                            st.success("봉제 작업을 시작합니다.")
                        
                        st.session_state["key_sewing_wait"] += 1 # 목록 선택 초기화
                        st.rerun()
                elif len(selected_indices) > 1:
                    st.info("ℹ️ 봉제 시작 처리는 한 번에 하나의 항목만 가능합니다. (작업지시서는 다중 출력 가능)")
        else:
            st.info("봉제 대기 중인 건이 없습니다.")
            
    # --- 2. 봉제중 탭 ---
    elif sub_menu == "봉제중 목록":
        st.subheader("봉제중 목록")
        
        # [NEW] 목록 갱신을 위한 키 초기화
        if "sewing_ing_key" not in st.session_state:
            st.session_state["sewing_ing_key"] = 0
            
        docs = db.collection("orders").where("status", "==", "봉제중").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            col_map = {
                "order_no": "발주번호", "sewing_partner": "봉제처", "sewing_type": "구분",
                "name": "제품명", "color": "색상", "stock": "수량", "sewing_start_date": "시작일"
            }
            display_cols = ["sewing_start_date", "sewing_type", "sewing_partner", "order_no", "name", "color", "stock"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 완료 처리할 항목을 선택하세요.")
            # [수정] 동적 키 적용하여 완료 후 선택 해제
            selection = st.dataframe(df[final_cols].rename(columns=col_map), width="stretch", on_select="rerun", selection_mode="single-row", key=f"df_sew_ing_{st.session_state['sewing_ing_key']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                
                # [FIX] 선택된 인덱스가 데이터프레임 범위를 벗어나는 경우 방지
                if idx >= len(df):
                    st.rerun()
                
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                st.markdown(f"### 봉제 완료 처리: **{sel_row['name']}**")
                
                tab_act1, tab_act2 = st.tabs(["봉제 완료 처리", "정보 수정 / 취소"])
                
                with tab_act1:
                    st.write("봉제 완료 정보를 입력하세요.")
                    c1, c2, c3 = st.columns(3)
                    s_end_date = c1.date_input("봉제완료일", datetime.date.today())
                    s_real_stock = c2.number_input("완료수량(장)", value=int(sel_row.get('stock', 0)), step=10)
                    s_defect_stock = c3.number_input("불량수량(장)", min_value=0, step=1, value=0, help="불량으로 빠지는 수량입니다.")
                    
                    # 외주봉제일 경우 단가/금액 입력
                    s_price = 0
                    s_total = 0
                    s_supply = 0
                    s_vat = 0
                    s_vat_inc = False
                    
                    if sel_row.get('sewing_type') == "외주봉제":
                        st.markdown("#### 외주 가공비 정산")
                        c3, c4 = st.columns(2)
                        s_price = c3.number_input("봉제단가(원)", min_value=0, step=1)
                        s_vat_inc = c4.checkbox("부가세 포함", value=False, key="sew_vat_check")
                        
                        base_calc = int(s_real_stock * s_price)
                        if s_vat_inc:
                            s_supply = int(base_calc / 1.1)
                            s_vat = base_calc - s_supply
                            s_total = base_calc
                        else:
                            s_supply = base_calc
                            s_vat = int(base_calc * 0.1)
                            s_total = base_calc + s_vat
                            
                        st.info(f"**봉제비용 합계**: {s_total:,}원 (공급가: {s_supply:,}원 / 부가세: {s_vat:,}원)")
                    
                    if st.button("봉제 완료 (출고대기로 이동)"):
                        # [수정] 불량 수량을 제외한 정품 수량만 다음 공정(출고)으로 이동
                        final_stock = max(0, s_real_stock - s_defect_stock)
                        
                        updates = {
                            "status": "봉제완료",
                            "sewing_end_date": str(s_end_date),
                            "stock": s_real_stock,
                            "stock": final_stock,
                            "sewing_defect_qty": s_defect_stock # 불량 수량 저장
                        }
                        if sel_row.get('sewing_type') == "외주봉제":
                            updates["sewing_unit_price"] = s_price
                            updates["sewing_amount"] = s_total
                            updates["sewing_supply"] = s_supply
                            updates["sewing_vat"] = s_vat
                            updates["vat_included"] = s_vat_inc
                        
                        db.collection("orders").document(sel_id).update(updates)
                        st.success("봉제 완료 처리되었습니다.")
                        st.session_state["sewing_ing_key"] += 1 # 키 증가로 목록 선택 초기화
                        st.rerun()
                            
                with tab_act2:
                    with st.form("sewing_edit_form"):
                        st.write("작업 정보 수정")
                        c1, c2 = st.columns(2)
                        e_date = c1.date_input("봉제시작일", datetime.datetime.strptime(sel_row['sewing_start_date'], "%Y-%m-%d").date() if sel_row.get('sewing_start_date') else datetime.date.today())
                        e_type = c2.radio("작업 구분", ["자체봉제", "외주봉제"], horizontal=True, index=0 if sel_row.get('sewing_type') == "자체봉제" else 1)
                        
                        e_partner = st.selectbox("봉제업체", sewing_partners if sewing_partners else ["직접입력"], index=sewing_partners.index(sel_row['sewing_partner']) if sel_row.get('sewing_partner') in sewing_partners else 0)
                        
                        if st.form_submit_button("수정 저장"):
                            updates = {
                                "sewing_start_date": str(e_date),
                                "sewing_type": e_type,
                                "sewing_partner": "자체" if e_type == "자체봉제" else e_partner
                            }
                            db.collection("orders").document(sel_id).update(updates)
                            st.success("수정되었습니다.")
                            st.session_state["sewing_ing_key"] += 1
                            st.rerun()
                    
                    st.markdown("#### 작업 취소")
                    if st.button("봉제 취소 (대기로 되돌리기)", type="primary"):
                        # [NEW] 병합 로직: 같은 발주번호의 대기중(염색완료)인 항목이 있으면 합침
                        siblings = list(db.collection("orders")\
                            .where("order_no", "==", sel_row['order_no'])\
                            .where("status", "==", "염색완료")\
                            .stream())
                        
                        merged = False
                        for sib in siblings:
                            sib_data = sib.to_dict()
                            # 안전장치: 제품코드와 색상이 같은지 확인 (발주번호가 같으면 보통 같음)
                            if sib_data.get('product_code') == sel_row.get('product_code') and \
                               sib_data.get('color') == sel_row.get('color'):
                                
                                new_stock = int(sib_data.get('stock', 0)) + int(sel_row.get('stock', 0))
                                db.collection("orders").document(sib.id).update({"stock": new_stock})
                                db.collection("orders").document(sel_id).delete()
                                merged = True
                                st.success(f"기존 대기 건과 병합되어 '염색완료' 상태로 복귀되었습니다. (합계: {new_stock}장)")
                                break
                        
                        if not merged:
                            db.collection("orders").document(sel_id).update({"status": "염색완료"})
                            st.success("취소되었습니다. (염색완료 상태로 복귀)")
                        
                        st.session_state["sewing_ing_key"] += 1
                        st.rerun()
        else:
            st.info("현재 봉제 중인 작업이 없습니다.")

    # --- 3. 봉제 완료 탭 ---
    elif sub_menu == "봉제 완료 목록":
        st.subheader("봉제 완료 목록")
        
        if "key_sewing_done" not in st.session_state:
            st.session_state["key_sewing_done"] = 0
        
        # 검색 및 엑셀 다운로드
        with st.form("search_sew_done"):
            c1, c2, c3 = st.columns([2, 1, 1])
            today = datetime.date.today()
            s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
            s_partner = c2.text_input("봉제업체")
            s_customer = c3.text_input("발주처")
            st.form_submit_button("🔍 조회")
            
        # 날짜 범위 계산
        if len(s_date) == 2:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[1], datetime.time.max)
        else:
            start_dt = datetime.datetime.combine(s_date[0], datetime.time.min)
            end_dt = datetime.datetime.combine(s_date[0], datetime.time.max)
            
        # [수정] 다음 공정으로 넘어간 내역도 조회되도록 상태 조건 확대
        target_statuses = ["봉제완료", "출고완료"]
        docs = db.collection("orders").where("status", "in", target_statuses).stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # 날짜 필터
            s_end = d.get('sewing_end_date')
            if s_end:
                try:
                    s_end_obj = datetime.datetime.strptime(s_end, "%Y-%m-%d")
                    if not (start_dt <= s_end_obj <= end_dt): continue
                except: continue
            else: continue
            
            # 업체 필터
            if s_partner and s_partner not in d.get('sewing_partner', ''):
                continue

            # 발주처 필터
            if s_customer and s_customer not in d.get('customer', ''):
                continue
                
            rows.append(d)
            
        rows.sort(key=lambda x: x.get('sewing_end_date', ''), reverse=True)
        
        if rows:
            df = pd.DataFrame(rows)
            
            # 합계 계산
            total_stock = df['stock'].sum() if 'stock' in df.columns else 0
            total_amount = df['sewing_amount'].sum() if 'sewing_amount' in df.columns else 0
            
            st.markdown(f"### 📊 합계: 수량 **{total_stock:,}장** / 금액 **{total_amount:,}원**")
            
            col_map = {
                "order_no": "발주번호", "sewing_partner": "봉제처", "sewing_end_date": "완료일",
                "name": "제품명", "color": "색상", "stock": "수량", "sewing_type": "구분",
                "sewing_unit_price": "단가", "sewing_amount": "금액", "sewing_defect_qty": "불량",
                "customer": "발주처"
            }
            display_cols = ["sewing_end_date", "sewing_type", "sewing_partner", "customer", "order_no", "name", "color", "stock", "sewing_defect_qty", "sewing_unit_price", "sewing_amount"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            df_display = df[final_cols].rename(columns=col_map)
            
            # 엑셀 및 인쇄 버튼
            c_exp1, c_exp2 = st.columns([1, 5])
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            c_exp1.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"봉제완료내역_{today}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 인쇄 옵션 설정
            with st.expander("🖨️ 인쇄 옵션 설정"):
                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", value="봉제 완료 내역", key="sd_title")
                p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="sd_ts")
                p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="sd_bs")
                p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="sd_pad")
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="sd_sd")
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="sd_dp")
                p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="sd_ds")
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", value=15, step=1, key="sd_mt")
                p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="sd_mb")
                p_m_left = po_c10.number_input("좌측", value=15, step=1, key="sd_ml")
                p_m_right = po_c11.number_input("우측", value=15, step=1, key="sd_mr")

            # [수정] utils의 generate_report_html 함수 사용
            if c_exp2.button("🖨️ 바로 인쇄하기", key="btn_print_sd"):
                options = {
                    'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                    'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                    'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
                }
                summary_text = f"합계 - 수량: {total_stock:,}장 / 금액: {total_amount:,}원"
                print_html = generate_report_html(p_title, df_display, summary_text, options)
                st.components.v1.html(print_html, height=0, width=0)

            st.write("🔽 수정하거나 취소할 항목을 선택하세요.")
            selection = st.dataframe(df_display, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key=f"df_sew_done_{st.session_state['key_sewing_done']}")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]

                # [FIX] 선택된 인덱스가 데이터프레임 범위를 벗어나는 경우를 방지 (삭제/상태변경 후 발생)
                if idx >= len(df):
                    # 선택 상태를 초기화하기 위해 리런
                    st.rerun()

                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                current_status = sel_row.get('status', '')
                if current_status != "봉제완료":
                    st.error(f"⛔ 현재 상태가 '**{current_status}**'이므로 이 단계에서 수정하거나 취소할 수 없습니다.")
                    st.info("이미 출고 처리가 된 경우, 출고 현황에서 출고를 취소해야 합니다.")
                else:
                    st.markdown(f"### 완료 정보 수정: **{sel_row['name']}**")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        with st.form("sewing_done_edit"):
                            st.write("완료 정보 수정")
                            new_end_date = st.date_input("봉제완료일", datetime.datetime.strptime(sel_row['sewing_end_date'], "%Y-%m-%d").date() if sel_row.get('sewing_end_date') else datetime.date.today())
                            new_stock = st.number_input("완료수량(정품)", value=int(sel_row.get('stock', 0)), step=10)
                            new_defect = st.number_input("불량수량(장)", value=int(sel_row.get('sewing_defect_qty', 0)), step=1)
                            
                            new_price = 0
                            if sel_row.get('sewing_type') == "외주봉제":
                                new_price = st.number_input("봉제단가(원)", value=int(sel_row.get('sewing_unit_price', 0)) if not pd.isna(sel_row.get('sewing_unit_price')) else 0, step=1)
                            
                            if st.form_submit_button("수정 저장"):
                                updates = {
                                    "sewing_end_date": str(new_end_date),
                                    "stock": new_stock,
                                    "sewing_defect_qty": new_defect
                                }
                                if sel_row.get('sewing_type') == "외주봉제":
                                    # 부가세 로직은 복잡하므로 단순 계산만 반영
                                    updates["sewing_unit_price"] = new_price
                                    updates["sewing_amount"] = int(new_stock * new_price)
                                    
                                db.collection("orders").document(sel_id).update(updates)
                                st.success("수정되었습니다.")
                                st.session_state["key_sewing_done"] += 1
                                st.rerun()
                    with c2:
                        st.write("**완료 취소**")
                        st.warning("상태를 다시 '봉제중'으로 되돌립니다.")
                        if st.button("완료 취소 (봉제중으로 복귀)", type="primary"):
                            db.collection("orders").document(sel_id).update({"status": "봉제중"})
                            st.success("복귀되었습니다.")
                            st.session_state["key_sewing_done"] += 1
                            st.rerun()
        else:
            st.info("조회된 봉제 완료 내역이 없습니다.")