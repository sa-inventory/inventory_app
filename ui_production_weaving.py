import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import generate_report_html, get_machines_list

def render_weaving(db, sub_menu=None, readonly=False):
    st.header("제직 현황" if not readonly else "제직 조회 (보기 전용)")
    if "weaving_df_key" not in st.session_state:
        st.session_state["weaving_df_key"] = 0
    st.info("발주된 건을 확인하고 제직 작업을 지시하거나, 완료된 건을 염색 공정으로 넘깁니다.")

    # [NEW] 제직 현황 카드 및 툴팁 스타일 정의
    st.markdown("""
    <style>
        .weaving-card {
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 10px;
            position: relative;
            cursor: help;
            transition: all 0.2s ease-in-out;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            text-align: center;
            height: 110px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        .weaving-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
            z-index: 10;
        }
        .wc-busy { background-color: #ffebee; border: 1px solid #ef9a9a; color: #c62828; }
        .wc-free { background-color: #f1f8e9; border: 1px solid #a5d6a7; color: #33691e; }
        .wc-header { font-weight: bold; font-size: 1.1em; margin-bottom: 5px; }
        .wc-body { font-size: 0.9em; line-height: 1.3; }
        
        /* Tooltip */
        .weaving-card .wc-tooltip {
            visibility: hidden;
            width: 240px;
            background-color: rgba(0, 0, 0, 0.9);
            color: #fff;
            text-align: left;
            border-radius: 6px;
            padding: 12px;
            position: absolute;
            z-index: 100;
            top: 100%; left: 50%; margin-left: -120px;
            opacity: 0; transition: opacity 0.3s;
            font-size: 0.85em; line-height: 1.5; pointer-events: none; margin-top: 8px;
        }
        .weaving-card .wc-tooltip::after {
            content: ""; position: absolute; bottom: 100%; left: 50%; margin-left: -5px;
            border-width: 5px; border-style: solid; border-color: transparent transparent rgba(0, 0, 0, 0.9) transparent;
        }
        .weaving-card:hover .wc-tooltip { visibility: visible; opacity: 1; }
    </style>
    """, unsafe_allow_html=True)

    # [공통] 제직기 설정 가져오기 (작업일지 등에서도 사용됨)
    # [최적화] 캐싱된 함수 사용
    machines_data = get_machines_list()
    
    # [수정] 데이터가 없거나 오류 발생 시 기본값 처리
    if not machines_data:
        # 설정이 없으면 기본 1~9호대 가상 데이터 사용 (호환성 유지)
        machines_data = [{"machine_no": i, "name": f"{i}호대", "model": "", "note": ""} for i in range(1, 10)]
    
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
                                cur_roll = item.get('completed_rolls', 0) + 1
                                
                                # [수정] 카드에는 핵심 정보만, 상세 정보는 툴팁으로 이동
                                card_html = f"""
                                <div class="weaving-card wc-busy">
                                    <div class="wc-header">{m_name}</div>
                                    <div class="wc-body">
                                        가동중<br>
                                        <span style="font-size:0.9em; font-weight:bold;">{item.get('name', '-')}</span><br>
                                        <span style="font-size:0.8em;">(전체 {roll_cnt}롤 중 {cur_roll}번째 롤)</span>
                                    </div>
                                    <div class="wc-tooltip">
                                        <strong>[{m_name}] 상세 정보</strong><hr style="margin:5px 0; border-color:#555;">
                                        <b>발주처:</b> {item.get('customer', '-')}<br>
                                        <b>제품명:</b> {item.get('name', '-')}<br>
                                        <b>종류:</b> {item.get('product_type', item.get('weaving_type', '-'))}<br>
                                        <b>규격:</b> {item.get('size', '-')}<br>
                                        <b>중량:</b> {item.get('weight', '-')}g<br>
                                        <b>수량:</b> {int(item.get('stock', 0)):,}장<br>
                                        <b>납품요청일:</b> {str(item.get('delivery_req_date', '-'))[:10]}<br>
                                        <b>진행:</b> 전체 {roll_cnt}롤 중 {cur_roll}번째 롤
                                    </div>
                                </div>
                                """
                                st.markdown(card_html, unsafe_allow_html=True)
                            else:
                                card_html = f"""
                                <div class="weaving-card wc-free">
                                    <div class="wc-header">{m_name}</div>
                                    <div class="wc-body">
                                        대기중<br>
                                        <span style="font-size:0.8em;">{m_desc if m_desc else '-'}</span>
                                    </div>
                                    <div class="wc-tooltip">
                                        <strong>[{m_name}] 상태 정보</strong><hr style="margin:5px 0; border-color:#555;">
                                        작업 대기중
                                    </div>
                                </div>
                                """
                                st.markdown(card_html, unsafe_allow_html=True)
            
            # [NEW] 새로고침 버튼 (하단 배치)
            rb_c1, rb_c2 = st.columns([8.5, 1.5])
            if rb_c2.button("🔄 현황 새로고침", key="refresh_weaving_dash", help="최신 제직 현황을 불러옵니다."):
                st.rerun()
        
        st.divider()

    # --- 1. 제직대기 탭 ---
    if sub_menu == "제직대기 목록":
        st.subheader("제직 대기 목록")
        
        # [NEW] 목록 갱신을 위한 키 초기화 (제직대기)
        if "key_weaving_wait" not in st.session_state:
            st.session_state["key_weaving_wait"] = 0
            
        # [NEW] 검색 UI 추가
        with st.expander("검색", expanded=True):
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
            
            # [수정] 모드 선택 토글 및 안내 문구
            c_head_1, c_head_2 = st.columns([0.75, 0.25])
            with c_head_2:
                cancel_mode = st.toggle("🔄 제직대기 취소(발주접수 되돌리기)", key="weav_cancel_mode_toggle", help="활성화하면 발주접수 상태로 되돌릴 항목을 다중 선택할 수 있습니다.")
            
            with c_head_1:
                if cancel_mode:
                    st.info("취소할 항목을 선택(체크)하고 하단의 '일괄 취소' 버튼을 누르세요.")
                    sel_mode = "multi-row"
                else:
                    st.write("🔽 제직기를 배정할 항목을 선택하세요.")
                    sel_mode = "single-row"

            # key="df_waiting" 추가로 사이드바 먹통 현상 해결
            selection = st.dataframe(
                df[final_cols].rename(columns=col_map), 
                width="stretch", 
                on_select="rerun", 
                selection_mode=sel_mode, 
                key=f"df_waiting_{st.session_state['key_weaving_wait']}"
            )
            
            if selection.selection.rows:
                if readonly:
                    st.info("🔒 조회 전용 모드입니다. (수정 불가)")
                else:
                    selected_indices = selection.selection.rows
                    
                    if cancel_mode:
                        # [NEW] 일괄 취소 모드 로직
                        selected_rows = df.iloc[selected_indices]
                        
                        st.divider()
                        st.markdown(f"#### 선택 항목 취소 ({len(selected_rows)}건)")
                        st.warning("선택한 항목들을 '발주접수' 상태로 되돌립니다.")
                        
                        if st.button("✅ 선택 항목 일괄 취소 (발주접수로 복귀)", type="primary", key="btn_batch_cancel_weav"):
                            batch = db.batch()
                            for idx, row in selected_rows.iterrows():
                                doc_ref = db.collection("orders").document(row['id'])
                                batch.update(doc_ref, {"status": "발주접수"})
                            batch.commit()
                            
                            st.success(f"{len(selected_rows)}건이 발주접수 상태로 되돌려졌습니다.")
                            st.session_state["key_weaving_wait"] += 1
                            st.rerun()
                    
                    else:
                        # [수정] 제직기 배정 모드 (단일 선택)
                        idx = selected_indices[0]
                        sel_row = df.iloc[idx]
                        sel_id = sel_row['id']
                        
                        st.divider()
                        
                        # [NEW] 닫기 버튼 (우측 상단 배치)
                        c_title, c_close = st.columns([8.5, 1.5])
                        with c_title:
                            st.markdown(f"### 제직기 배정: **{sel_row['name']}**")
                        with c_close:
                            if st.button("❌ 닫기", key="close_weav_assign", use_container_width=True):
                                st.session_state["key_weaving_wait"] += 1
                                st.rerun()

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
                                
                                # [수정] 저장 직전 DB 실시간 상태 재확인 (동시성 제어)
                                # 현재 해당 제직기로 '제직중'인 작업이 있는지 쿼리
                                check_busy = list(db.collection("orders").where("status", "==", "제직중").where("machine_no", "==", int(sel_m_no)).stream())
                                
                                if check_busy:
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
                    
                    # [FIX] 제직 취소 기능은 readonly가 아닐 때만 표시
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
        with st.expander("검색", expanded=True):
            with st.form("search_weaving_done"):
                c1, c2, c3 = st.columns([2, 1, 1])
                today = datetime.date.today()
                s_date = c1.date_input("조회 기간 (완료일)", [today - datetime.timedelta(days=30), today])
                s_cust = c2.text_input("발주처 검색")
                s_prod = c3.text_input("제품명 검색")
                st.form_submit_button("조회")

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
            
            st.divider()

            # 인쇄 옵션 설정
            with st.expander("인쇄 옵션 설정"):
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
                
                po_c12, po_c13 = st.columns(2)
                wd_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="wd_bo")
                wd_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="wd_bi")

            # [수정] 버튼 하단 배치 (좌측 끝: 엑셀, 우측 끝: 인쇄)
            c_btn_xls, c_btn_gap, c_btn_prt = st.columns([1.5, 5, 1.5])
            
            with c_btn_xls:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_display.to_excel(writer, index=False)
                
                st.download_button(
                    label="💾 엑셀 다운로드",
                    data=buffer.getvalue(),
                    file_name=f"제직완료내역_{today}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            with c_btn_prt:
                if st.button("🖨️ 인쇄하기", key="btn_print_wd", use_container_width=True):
                    options = {
                        'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                        'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                        'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none",
                        'bo': wd_bo, 'bi': wd_bi
                    }
                    summary_text = f"합계 - 생산수량: {total_stock:,}장 / 생산중량: {total_weight:,.1f}kg"
                    print_html = generate_report_html(p_title, df_display, summary_text, options)
                    st.components.v1.html(print_html, height=0, width=0)
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
        
        # 주간 섹션
        st.markdown("#### 주간 작업")
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
        else:
            st.info("기록 없음")
            
        st.markdown("##### 📝 야간근무자 전달사항")
        d_note = notes_data.get('day_to_night_notes', '-')
        st.warning(d_note)

        st.divider()

        # 야간 섹션
        st.markdown("#### 야간 작업")
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
        else:
            st.info("기록 없음")

        st.markdown("##### 📝 주간근무자 전달사항")
        n_note = notes_data.get('night_to_day_notes', '-')
        st.warning(n_note)
        
        st.divider()

        # 인쇄 옵션 설정 (하단으로 이동)
        with st.expander("인쇄 옵션 설정"):
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
            
            po_c12, po_c13 = st.columns(2)
            wl_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="wl_bo")
            wl_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="wl_bi")

        # 인쇄용 HTML 생성 (옵션 설정 후)
        print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        print_date_display = "block" if p_show_date else "none"
        work_date_display = "block" if p_show_work_date else "none"

        style = f"""<style>
            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: {p_body_size}px; border: {wl_bo}px solid #444; }}
            th, td {{ border: {wl_bi}px solid #444; padding: {p_padding}px; text-align: left; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: {p_body_size}px; table-layout: fixed; border: {wl_bo}px solid #444; }}
            th, td {{ border: {wl_bi}px solid #444; padding: {p_padding}px; text-align: left; word-wrap: break-word; }}
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

        # HTML 내용 추가 (주간)
        html_content += "<div class='section-title'>주간 작업</div>"
        if day_logs:
            df_day = pd.DataFrame(day_logs)
            df_day['log_time'] = df_day['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
            html_content += df_day[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'제직기','content':'내용','author':'작성자'}).to_html(index=False, border=1)
        else:
            html_content += "<p>기록 없음</p>"
        html_content += f"<div class='section-title'>📝 야간근무자 전달사항</div><div class='note-box'>{d_note}</div>"

        # HTML 내용 추가 (야간)
        html_content += "<div class='section-title'>야간 작업</div>"
        if night_logs:
            df_night = pd.DataFrame(night_logs)
            df_night['log_time'] = df_night['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
            html_content += df_night[['log_time', 'machine_no', 'content', 'author']].rename(columns={'log_time':'시간','machine_no':'제직기','content':'내용','author':'작성자'}).to_html(index=False, border=1)
        else:
            html_content += "<p>기록 없음</p>"
        html_content += f"<div class='section-title'>📝 주간근무자 전달사항</div><div class='note-box'>{n_note}</div>"
        html_content += "</body></html>"
        
        # [수정] 버튼 하단 배치 (좌측 끝: 엑셀, 우측 끝: 인쇄)
        c_btn_xls, c_btn_gap, c_btn_prt = st.columns([1.5, 5, 1.5])
        
        with c_btn_xls:
            # 작업일지 엑셀 데이터 생성
            xls_data = []
            for l in day_logs:
                l_copy = l.copy()
                l_copy['근무조'] = '주간'
                xls_data.append(l_copy)
            for l in night_logs:
                l_copy = l.copy()
                l_copy['근무조'] = '야간'
                xls_data.append(l_copy)
            
            if xls_data:
                df_xls = pd.DataFrame(xls_data)
                # 시간 포맷팅 및 컬럼 정리
                df_xls['log_time'] = df_xls['log_time'].apply(lambda x: x.strftime('%H:%M') if hasattr(x, 'strftime') else str(x)[11:16])
                cols_map = {'log_date': '일자', 'shift': '근무조', 'log_time': '시간', 'machine_no': '제직기', 'content': '내용', 'author': '작성자'}
                final_xls = df_xls[['log_date', 'shift', 'log_time', 'machine_no', 'content', 'author']].rename(columns=cols_map)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    final_xls.to_excel(writer, index=False)
                
                st.download_button(label="💾 엑셀 다운로드", data=buffer.getvalue(), file_name=f"작업일지_{view_date}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            else:
                st.download_button("💾 엑셀 다운로드", b"", disabled=True, use_container_width=True)

        with c_btn_prt:
            if st.button("🖨️ 인쇄하기", use_container_width=True):
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
        
        prod_date_str = st.selectbox("조회일자 선택", sorted_prod_dates if sorted_prod_dates else [str(datetime.date.today())], key="prodlog_view_date")
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
            st.markdown(f"### {prod_date} 생산일지")
            st.dataframe(df_display, hide_index=True, width="stretch")
            
            # 엑셀 다운로드 준비
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
                
            # 인쇄 옵션 설정
            with st.expander("인쇄 옵션 설정"):
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
                
                po_c12, po_c13 = st.columns(2)
                pl_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="pl_bo")
                pl_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="pl_bi")

            # [수정] utils의 generate_report_html 함수 사용
            options = {
                'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none",
                'bo': pl_bo, 'bi': pl_bi
            }
            print_html = generate_report_html(p_title, df_display, "", options)
            
            # [수정] 버튼 하단 배치 (좌측 끝: 엑셀, 우측 끝: 인쇄)
            c_btn_xls, c_btn_gap, c_btn_prt = st.columns([1.5, 5, 1.5])
            
            with c_btn_xls:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_display.to_excel(writer, index=False)
                st.download_button(label="💾 엑셀 다운로드", data=buffer.getvalue(), file_name=f"생산일지_{prod_date}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            with c_btn_prt:
                if st.button("🖨️ 인쇄하기", use_container_width=True):
                    final_print_html = print_html.replace(
                        "</head>",
                        """<style> @media screen { body { display: none; } } </style></head>"""
                    ).replace(
                        "<body>",
                        '<body onload="window.print();">'
                    )
                    st.components.v1.html(final_print_html, height=0, width=0)
        else:
            st.info(f"{prod_date}에 완료된 생산 내역이 없습니다.")
