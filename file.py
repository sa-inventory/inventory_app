import streamlit as st
import pandas as pd
import datetime
import io
import uuid
from firebase_admin import firestore
from utils import get_partners, get_common_codes, search_address_api, generate_report_html, get_partners_map, get_db, save_user_settings, load_user_settings
from ui_inventory import render_inventory_logic

# [NEW] 숫자 한글 변환 함수 (공통 사용을 위해 밖으로 이동)
def num_to_korean(num):
    units = ['', '십', '백', '천']
    large_units = ['', '만', '억', '조', '경']
    digits = ['', '일', '이', '삼', '사', '오', '육', '칠', '팔', '구']
    
    if not isinstance(num, int) or num < 0: return ""
    if num == 0: return '영'
        
    result_parts = []
    num_str = str(num)
    
    while num_str:
        part, num_str = num_str[-4:], num_str[:-4]
        if int(part) > 0:
            part_korean = ""
            for i, digit_char in enumerate(reversed(part)):
                digit = int(digit_char)
                if digit > 0:
                    num_word = digits[digit] if not (digit == 1 and i > 0) else ""
                    part_korean = num_word + units[i] + part_korean
            result_parts.append(part_korean)
    return ''.join(f"{part}{unit}" for i, (part, unit) in enumerate(zip(reversed(result_parts), reversed(large_units[:len(result_parts)]))) if part)

def render_shipping_operations(db, sub_menu):
    st.header("출고 작업")

    # [FIX] 출고 완료 후에는 명세서 발행 UI만 표시하고 나머지 로직은 중단
    if st.session_state.get("last_shipped_data") is not None:
        st.success("✅ 출고가 완료되었습니다.")
        if st.button("확인 (목록 새로고침)", type="primary", use_container_width=True):
            st.session_state["last_shipped_data"] = None
            st.rerun()
        
        st.stop()

    st.info("완성된 제품(봉제완료)을 출고 처리합니다.")
    
    if "ship_op_key" not in st.session_state:
        st.session_state["ship_op_key"] = 0

    shipping_partners = get_partners("배송업체")
    shipping_methods = get_common_codes("shipping_methods", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"])
    
    # [NEW] 주소 검색 모달 (Dialog) - 출고 작업용
    if "show_ship_addr_dialog" not in st.session_state:
        st.session_state.show_ship_addr_dialog = False

    @st.dialog("주소 검색")
    def show_address_search_modal_ship():
        if "s_addr_keyword" not in st.session_state: st.session_state.s_addr_keyword = ""
        if "s_addr_page" not in st.session_state: st.session_state.s_addr_page = 1

        with st.form("addr_search_form_ship"):
            keyword_input = st.text_input("도로명 또는 지번 주소 입력", value=st.session_state.s_addr_keyword, placeholder="예: 세종대로 209")
            if st.form_submit_button("검색"):
                st.session_state.s_addr_keyword = keyword_input
                st.session_state.s_addr_page = 1
                st.rerun()

        if st.session_state.s_addr_keyword:
            results, common, error = search_address_api(st.session_state.s_addr_keyword, st.session_state.s_addr_page)
            if error: st.error(error)
            elif results:
                st.session_state['s_addr_results'] = results
                st.session_state['s_addr_common'] = common
            else: st.warning("검색 결과가 없습니다.")
        
        if 's_addr_results' in st.session_state:
            for idx, item in enumerate(st.session_state['s_addr_results']):
                road = item['roadAddr']
                zip_no = item['zipNo']
                full_addr = f"({zip_no}) {road}"
                if st.button(f"{full_addr}", key=f"sel_s_{zip_no}_{idx}"):
                    st.session_state["ship_addr_input"] = full_addr
                    st.session_state.show_ship_addr_dialog = False
                    for k in ['s_addr_keyword', 's_addr_page', 's_addr_results', 's_addr_common']:
                        if k in st.session_state: del st.session_state[k]
                    st.rerun()
            
            # Pagination
            common_info = st.session_state.get('s_addr_common', {})
            if common_info:
                total_count = int(common_info.get('totalCount', 0))
                current_page = int(common_info.get('currentPage', 1))
                count_per_page = int(common_info.get('countPerPage', 10))
                total_pages = (total_count + count_per_page - 1) // count_per_page if total_count > 0 else 1
                
                if total_pages > 1:
                    st.divider()
                    p_cols = st.columns([1, 2, 1])
                    if p_cols[0].button("◀ 이전", disabled=(current_page <= 1), key="s_prev"):
                        st.session_state.s_addr_page -= 1
                        st.rerun()
                    p_cols[1].write(f"페이지 {current_page} / {total_pages}")
                    if p_cols[2].button("다음 ▶", disabled=(current_page >= total_pages), key="s_next"):
                        st.session_state.s_addr_page += 1
                        st.rerun()

        st.divider()
        if st.button("닫기", key="close_addr_ship", use_container_width=True):
            st.session_state.show_ship_addr_dialog = False
            st.rerun()

    # [수정] 작업 모드 선택 (버튼 토글 방식)
    if "ship_op_mode" not in st.session_state:
        st.session_state["ship_op_mode"] = "주문접수 보기"

    c_mode1, c_mode2 = st.columns([1, 1])
    with c_mode1:
        if st.button("주문접수 기준으로 보기", 
                     type="primary" if st.session_state["ship_op_mode"] == "주문접수 보기" else "secondary", 
                     use_container_width=True, 
                     key="btn_ship_mode_order"):
            st.session_state["ship_op_mode"] = "주문접수 보기"
            st.rerun()
    with c_mode2:
        if st.button("제품코드 or 제품명 기준으로 보기", 
                     type="primary" if st.session_state["ship_op_mode"] == "제품기준 보기" else "secondary", 
                     use_container_width=True, 
                     key="btn_ship_mode_product"):
            st.session_state["ship_op_mode"] = "제품기준 보기"
            st.rerun()

    if st.session_state["ship_op_mode"] == "주문접수 보기":
        st.subheader("주문별 출고 (발주번호 기준)")
        
        # [NEW] 검색 및 필터 UI
        with st.expander("검색", expanded=True):
            # [수정] 레이아웃 변경: 한 줄로 배치 및 날짜 입력 폭 축소
            c_f1, c_f2, c_f3 = st.columns([1.2, 1, 2])
            today = datetime.date.today()
            # [수정] 기간 검색 (접수일 기준) - 기본 3개월
            s_date_range = c_f1.date_input("접수일 기간", [today - datetime.timedelta(days=90), today], key="ship_ord_date_range")
            
            search_criteria = c_f2.selectbox("검색 기준", ["전체(통합)", "제품코드", "발주처", "제품명", "발주번호"], key="ship_ord_criteria")
            search_keyword = c_f3.text_input("검색어 입력", key="ship_ord_keyword")

        docs = db.collection("orders").where("status", "==", "봉제완료").stream()
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
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            df = pd.DataFrame(rows)
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)

            # 3. 키워드 검색 필터
            if search_keyword:
                search_keyword = search_keyword.lower()
                if search_criteria == "전체(통합)":
                     mask = df.apply(lambda x: search_keyword in str(x.get('product_code', '')).lower() or
                                              search_keyword in str(x.get('customer', '')).lower() or
                                              search_keyword in str(x.get('name', '')).lower() or
                                              search_keyword in str(x.get('order_no', '')).lower() or
                                              search_keyword in str(x.get('note', '')).lower(), axis=1)
                     df = df[mask]
                elif search_criteria == "제품코드":
                    df = df[df['product_code'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "발주처":
                    df = df[df['customer'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품명":
                    df = df[df['name'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "발주번호":
                    df = df[df['order_no'].astype(str).str.lower().str.contains(search_keyword, na=False)]

            # [NEW] 임의 등록 재고 발주번호 마스킹 (STOCK-으로 시작하면 -로 표시)
            if 'order_no' in df.columns:
                df['order_no'] = df['order_no'].apply(lambda x: '-' if str(x).startswith('STOCK-') else x)

            col_map = {
                "product_code": "제품코드", "order_no": "발주번호", "date": "접수일", 
                "customer": "발주처", "name": "제품명", "color": "색상", "weight": "중량(g)", "size": "사이즈", "stock": "수량",
                "delivery_to": "납품처", "delivery_contact": "연락처", "delivery_address": "주소", "note": "비고"
            }
            display_cols = ["product_code", "order_no", "date", "customer", "name", "color", "weight", "size", "stock", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            # [수정] 테이블 우측 상단에 '모든 품목 조회' 체크박스 배치
            c_h1, c_h2 = st.columns([6, 1])
            c_h1.write("🔽 출고할 항목을 선택(체크)하세요. (다중 선택 가능)")
            show_all_items = c_h2.checkbox("모든 품목 조회", value=False, help="체크하면 재고가 0인 품목도 표시됩니다.", key="ship_ord_show_all")
            
            # [수정] 재고 필터 적용 (기본: 재고 > 0)
            df['stock'] = pd.to_numeric(df['stock'], errors='coerce').fillna(0).astype(int)
            if not show_all_items:
                df = df[df['stock'] > 0]
            
            # [NEW] 동적 높이 계산 (행당 약 35px, 최대 20행 700px)
            table_height = min((len(df) + 1) * 35 + 3, 700)
            
            selection = st.dataframe(
                df[final_cols].rename(columns=col_map),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                height=table_height,
                key=f"ship_op_list_{st.session_state['ship_op_key']}"
            )
            
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]
                
                st.divider()
                st.markdown(f"### 출고 정보 입력 (선택된 {len(selected_rows)}건)")

                st.markdown("##### 1. 출고 품목 상세 입력")
                
                # [NEW] 취소된 항목 관리 (세션 상태)
                if "ship_ignored_ids" not in st.session_state:
                    st.session_state["ship_ignored_ids"] = set()
                
                # [NEW] 선택된 행 중 취소되지 않은 것만 필터링
                valid_rows = selected_rows[~selected_rows['id'].isin(st.session_state["ship_ignored_ids"])]
                
                if valid_rows.empty:
                    st.warning("출고할 품목이 없습니다.")

                staging_data = []
                for idx, row in valid_rows.iterrows():
                    with st.container(border=True):
                        # [NEW] 1. 제품 정보 한 줄 표시
                        c_info, c_cancel = st.columns([8.8, 1.2])
                        stock = int(row.get('stock', 0))
                        price = int(row.get('shipping_unit_price', 0))
                        
                        with c_info:
                            # 이모지 제거
                            info_line = f"**{row.get('name')}** ({row.get('color', '')}/{row.get('size', '')}) | 중량: {row.get('weight', 0)}g | **현재고: {stock:,}** | 기본단가: {price:,}원"
                            st.markdown(info_line, unsafe_allow_html=True)
                        
                        with c_cancel:
                            if st.button("취소", key=f"cancel_item_{row['id']}", help="출고 목록에서 제외"):
                                st.session_state["ship_ignored_ids"].add(row['id'])
                                st.rerun()

                        # [NEW] 2. 입력 필드 (하단 정렬, 기본값 0)
                        c_qty, c_price, c_note = st.columns([1.5, 1, 2], vertical_alignment="bottom")
                        
                        with c_qty:
                            qty_key = f"ship_qty_{row['id']}"
                            chk_key = f"ship_all_chk_{row['id']}"

                            qc1, qc2 = st.columns([1, 1.5])
                            qc1.markdown("출고수량")
                            is_ship_all = qc2.checkbox("전량", key=chk_key)
                            
                            # 기본값 0, 전량 체크 시 재고량
                            current_qty = st.session_state.get(qty_key, 0)
                            if is_ship_all:
                                current_qty = stock
                            
                            qty = st.number_input("출고수량", min_value=0, max_value=stock, value=current_qty, step=10, key=qty_key, label_visibility="collapsed")

                        with c_price:
                            st.markdown("단가(원)")
                            price_input = st.number_input("단가", min_value=0, value=price, step=100, key=f"ship_price_{row['id']}", label_visibility="collapsed")
                        
                        with c_note:
                            st.markdown("비고")
                            note_input = st.text_input("비고", value=row.get('note', ''), placeholder="비고 사항 입력", key=f"ship_note_{row['id']}", label_visibility="collapsed")
                        
                    staging_data.append({
                        "id": row['id'],
                        "제품명": row.get('name'),
                        "현재고": stock,
                        "출고수량": qty,
                        "단가": price_input,
                        "비고": note_input
                    })
                
                edited_staging = pd.DataFrame(staging_data)
                
                # [NEW] 수량이 0인 항목은 계산 및 저장에서 제외
                valid_staging = edited_staging[edited_staging['출고수량'] > 0] if not edited_staging.empty else pd.DataFrame()

                total_ship_qty = valid_staging['출고수량'].sum() if not valid_staging.empty else 0
                total_est_amt = (valid_staging['출고수량'] * valid_staging['단가']).sum() if not valid_staging.empty else 0
                
                is_valid_qty = True
                if not valid_staging.empty:
                    for _, row in valid_staging.iterrows():
                        if row['출고수량'] > row['현재고']:
                            st.error(f"출고수량 확인(재고부족): {row['제품명']}")
                            is_valid_qty = False

                st.markdown("##### 2. 배송 및 운임 정보")
                
                # [FIX] 출고 정보 입력을 form으로 묶어 버튼 클릭 시 비활성화되도록 처리
                with st.container():
                    c1, c2, c3 = st.columns(3)
                    s_date = c1.date_input("출고일자", datetime.date.today())
                    s_method = c2.selectbox("배송방법", shipping_methods)
                    s_carrier = c3.selectbox("배송업체", ["직접입력"] + shipping_partners)
                    if s_carrier == "직접입력":
                        final_carrier = c3.text_input("업체명 직접입력", placeholder="")
                    else:
                        final_carrier = s_carrier
                    
                    st.markdown("##### 납품처 정보")
                    first_row = selected_rows.iloc[0]
                    
                    # [NEW] 선택 변경 감지 및 주소 필드 초기화
                    if "last_ship_sel_indices" not in st.session_state:
                        st.session_state["last_ship_sel_indices"] = []
                    
                    if st.session_state["last_ship_sel_indices"] != selected_indices:
                        # [FIX] NaN 값 처리 (text_input 오류 방지)
                        addr_val = first_row.get('delivery_address')
                        st.session_state["ship_addr_input"] = str(addr_val) if addr_val and not pd.isna(addr_val) else ""
                        st.session_state["ship_addr_detail_input"] = ""
                        st.session_state["last_ship_sel_indices"] = selected_indices
                        # [FIX] 선택 변경 시 팝업 강제 닫기 (자동 실행 방지)
                        st.session_state.show_ship_addr_dialog = False

                    # [수정] 레이아웃 변경: 납품처/연락처(1줄) -> 주소/상세주소(1줄)
                    c_d1, c_d2 = st.columns(2)
                    # [FIX] NaN 값 처리
                    val_to = first_row.get('delivery_to', '')
                    val_contact = first_row.get('delivery_contact', '')
                    d_to = c_d1.text_input("납품처명", value=str(val_to) if pd.notna(val_to) else '')
                    d_contact = c_d2.text_input("납품연락처", value=str(val_contact) if pd.notna(val_contact) else '')
                    
                    # [FIX] 주소 입력 필드를 form 안으로 이동
                    c_addr1, c_addr2, c_addr3 = st.columns([3.5, 2, 0.5], vertical_alignment="bottom")
                    d_addr = c_addr1.text_input("납품주소", key="ship_addr_input")
                    d_addr_detail = c_addr2.text_input("상세주소", key="ship_addr_detail_input")
                    # [FIX] 버튼 키를 동적으로 생성하여 선택 변경 시 상태 간섭 원천 차단
                    if c_addr3.button("🔍 주소", key=f"btn_search_ship_addr_{selected_indices}", use_container_width=True):
                        st.session_state.show_ship_addr_dialog = True
                    s_note = st.text_area("비고 (송장번호/차량번호 등)", placeholder="예: 경동택배 123-456-7890")

                    # [FIX] 부가세 포함 기본 체크
                    s_vat_inc = st.checkbox("단가에 부가세 포함", value=True)
                    if s_vat_inc:
                        s_supply_price = int(total_est_amt / 1.1)
                        s_vat = total_est_amt - s_supply_price
                    else:
                        s_supply_price = total_est_amt
                        s_vat = int(total_est_amt * 0.1)
                        total_est_amt += s_vat
                        
                    st.info(f"💰 **예상 합계**: 수량 {total_ship_qty:,}장 / 금액 {total_est_amt:,}원 (공급가 {s_supply_price:,} + 부가세 {s_vat:,})")

                    # [NEW] 운임비 입력 (리스트 형태)
                    st.markdown("##### 운임비 설정")
                    
                    if "ship_cost_list" not in st.session_state:
                        st.session_state["ship_cost_list"] = [{"내용": "택배비", "건수": 1, "단가": 0}]
                    
                    cost_items = st.session_state["ship_cost_list"]
                    indices_to_remove = []
                    total_shipping_cost = 0
                    
                    for i, item in enumerate(cost_items):
                        cc1, cc2, cc3, cc4 = st.columns([2, 1, 1.5, 0.8], vertical_alignment="bottom")
                        with cc1:
                            if i == 0: st.markdown("항목명")
                            item['내용'] = st.text_input("항목명", value=item['내용'], key=f"sc_name_{i}", label_visibility="collapsed")
                        with cc2:
                            if i == 0: st.markdown("건수")
                            item['건수'] = st.number_input("건수", min_value=1, value=item['건수'], step=1, key=f"sc_count_{i}", label_visibility="collapsed")
                        with cc3:
                            if i == 0: st.markdown("단가")
                            item['단가'] = st.number_input("단가", min_value=0, value=item['단가'], step=500, key=f"sc_price_{i}", label_visibility="collapsed")
                        with cc4:
                            if st.button("삭제", key=f"sc_del_{i}"):
                                indices_to_remove.append(i)
                        total_shipping_cost += item['건수'] * item['단가']

                    if indices_to_remove:
                        for i in sorted(indices_to_remove, reverse=True):
                            del st.session_state["ship_cost_list"][i]
                        st.rerun()
                        
                    if st.button("➕ 운임비 항목 추가"):
                        st.session_state["ship_cost_list"].append({"내용": "", "건수": 1, "단가": 0})
                        st.rerun()

                    st.write(f"**🚛 운임비 합계: {total_shipping_cost:,}원**")

                    # [수정] 운임비 적용 방식 선택 (기본값: 묶음-마지막행)
                    s_cost_mode = st.radio("운임비 적용 방식", ["묶음 운임비(마지막행 포함)", "건당 운임비"], horizontal=True, help="묶음 운임비: 목록의 맨 마지막 항목에만 운임비 전액을 부과합니다. (거래명세서 하단 표시용)")

                    submitted = st.button("출고하기", type="primary", disabled=not is_valid_qty, use_container_width=True, key="submit_ship_op")

                # 주소 검색 팝업 표시
                if st.session_state.show_ship_addr_dialog:
                    show_address_search_modal_ship()

                if submitted:
                    if valid_staging.empty:
                        st.error("출고할 품목의 수량을 입력해주세요 (0 이상).")
                        st.stop()

                    # [NEW] 운임비 상세 내역 리스트 변환 (DB 저장용)
                    cost_lines = []
                    for item in st.session_state["ship_cost_list"]:
                        if item['단가'] > 0 or item['건수'] > 0:
                            cost_lines.append({ "name": item['내용'], "qty": item['건수'], "price": item['단가'] })

                    # [수정] 0인 항목 제외한 valid_staging 사용
                    total_items = len(valid_staging)
                    last_idx = valid_staging.index[-1] if total_items > 0 else -1
                    
                    shipped_rows = [] # 명세서 발행용 데이터 수집

                    for idx, row in valid_staging.iterrows():
                        doc_id = row['id']
                        ship_qty = int(row['출고수량'])
                        s_unit_price = int(row['단가'])
                        s_note_item = str(row['비고'])
                        
                        # [수정] 운임비 계산 로직 변경
                        cost_per_item = 0
                        current_cost_lines = []

                        if total_shipping_cost > 0:
                            if s_cost_mode == "건당 운임비":
                                cost_per_item = total_shipping_cost
                                current_cost_lines = cost_lines
                            else: # 묶음 운임비(마지막행 포함)
                                # 현재 처리 중인 행이 데이터프레임의 마지막 행인지 확인
                                if idx == last_idx:
                                    cost_per_item = total_shipping_cost
                                    current_cost_lines = cost_lines
                                else:
                                    cost_per_item = 0
                                    current_cost_lines = []
                        
                        update_data = {
                            "status": "출고완료",
                            "shipping_date": datetime.datetime.combine(s_date, datetime.datetime.now().time()),
                            "shipping_method": s_method,
                            "shipping_carrier": final_carrier,
                            "shipping_cost": cost_per_item,
                            "shipping_cost_lines": current_cost_lines, # [NEW] 상세 내역 저장
                            "shipping_unit_price": s_unit_price,
                            "vat_included": s_vat_inc,
                            "delivery_to": d_to,
                            "delivery_contact": d_contact,
                            "delivery_address": f"{d_addr} {d_addr_detail}".strip(),
                            "note": s_note_item if s_note_item else s_note # 개별 비고가 있으면 우선, 없으면 공통 비고
                        }
                        
                        # 부분 출고 로직 (수량이 현재고보다 적을 때)
                        current_stock = int(row['현재고'])
                        if ship_qty < current_stock:
                            doc_ref = db.collection("orders").document(doc_id)
                            org_data = doc_ref.get().to_dict()
                            new_ship_doc = org_data.copy()
                            new_ship_doc.update(update_data)
                            new_ship_doc['stock'] = ship_qty
                            new_ship_doc['parent_id'] = doc_id
                            db.collection("orders").add(new_ship_doc)
                            doc_ref.update({"stock": current_stock - ship_qty})
                            
                            # 명세서용 데이터 추가
                            new_ship_doc['id'] = "new_doc" # 임시 ID
                            shipped_rows.append(new_ship_doc)
                        else:
                            db.collection("orders").document(doc_id).update(update_data)
                            
                            # 명세서용 데이터 추가 (기존 데이터 + 업데이트 데이터)
                            updated_doc = row.to_dict() if hasattr(row, 'to_dict') else row.copy()
                            updated_doc.update(update_data)
                            updated_doc['stock'] = ship_qty
                            shipped_rows.append(updated_doc)
                    
                    st.success(f"{len(selected_rows)}건 출고 처리 완료!")
                    
                    # [NEW] 완료 후 취소 목록 초기화
                    if "ship_ignored_ids" in st.session_state:
                        del st.session_state["ship_ignored_ids"]

                    # [NEW] 출고된 데이터를 세션에 저장하고 리런
                    st.session_state["last_shipped_data"] = pd.DataFrame(shipped_rows)
                    st.session_state["ship_op_key"] += 1
                    st.rerun()

        else:
            st.info("출고 대기 중인 건이 없습니다.")

    else: # 제품별 보기 (재고순)
        st.subheader("제품별 일괄 출고")
        # 재고 현황 로직 재사용 (출고 기능 포함)
        render_inventory_logic(db, allow_shipping=True)

# [NEW] 출고 내역 조회 캐싱 함수 (DB 읽기 비용 절감)
@st.cache_data(ttl=60) # 1분간 캐시 유지
def load_shipping_orders(start_dt, end_dt):
    db = get_db()
    # 날짜 필터링하여 쿼리
    docs = db.collection("orders").where("shipping_date", ">=", start_dt).where("shipping_date", "<=", end_dt).stream()
    data = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        # Datetime 객체는 캐싱 시 문제 없으나, 타임존 정보가 있으면 제거
        if d.get('shipping_date') and hasattr(d['shipping_date'], 'tzinfo'):
            d['shipping_date'] = d['shipping_date'].replace(tzinfo=None)
        data.append(d)
    return data

def render_shipping_status(db, sub_menu):
    st.header("출고 현황")
    st.info("출고된 내역을 조회하고 거래명세서를 발행합니다.")
    user_id = st.session_state.get("user_id")

    # [NEW] 거래명세서 설정을 위한 세션 상태 초기화
    if "stmt_settings" not in st.session_state:
        # 회사 정보 먼저 로드
        comp_doc = db.collection("settings").document("company_info").get()
        comp_info = comp_doc.to_dict() if comp_doc.exists else {}
        
        default_settings = {
            "opt_type": "공급받는자용", "opt_merge": True, "opt_inc_ship": True,
            "opt_show_sign": True, "opt_hide_price": False, "opt_show_logo": True,
            "opt_logo_height": 50, "opt_show_stamp": True, "opt_sw": 50, "opt_st": -10, "opt_sr": 0,
            "opt_show_appr": False, "opt_ac": 3,
            "opt_at_0": "담당", "opt_at_1": "검토", "opt_at_2": "승인", "opt_at_3": "이사", "opt_at_4": "사장",
            "bo": 1.0, "bi": 0.5, "tb": 1.0,
            "mt": 10, "mb": 10, "ml": 10, "mr": 10,
            "title": "거 래 명 세 서", "ts": 24, "fs": 12, "pad": 5,
            "rows": 18,
            "w_date": 5, "w_item": 25, "w_spec": 15, "w_qty": 8,
            "w_price": 10, "w_supply": 12, "w_tax": 10, "w_note": 15,
            "opt_bank": True, "opt_vat_chk": False,
            "opt_note": comp_info.get('note', '')
        }
        
        # [NEW] DB에서 사용자 설정 로드 (없으면 기본값 사용)
        st.session_state["stmt_settings"] = load_user_settings(user_id, "stmt_settings", default_settings)
    
    shipping_partners = get_partners("배송업체")
    
    # [NEW] 거래처 정보 미리 가져오기 (공급받는자 상세 표시용)
    # [최적화] 매번 DB를 조회하지 않고 캐싱된 함수 사용
    partners_map = get_partners_map()

    if sub_menu == "출고내역":
        st.subheader("출고 목록")
        
        if "key_ship_done" not in st.session_state:
            st.session_state["key_ship_done"] = 0

        # [수정] 검색 필터 UI 개선 (실시간 반영을 위해 form 제거 및 expander 활용)
        with st.expander("검색", expanded=True):
            # [NEW] 날짜 검색 로직 변경 (기간 선택 라디오 버튼 추가)
            if "ship_start_date" not in st.session_state:
                st.session_state["ship_start_date"] = datetime.date.today() - datetime.timedelta(days=30)
            if "ship_end_date" not in st.session_state:
                st.session_state["ship_end_date"] = datetime.date.today()
            if "ship_date_radio" not in st.session_state:
                st.session_state["ship_date_radio"] = "1개월"

            def on_ship_date_radio_change():
                val = st.session_state["ship_date_radio"]
                today = datetime.date.today()
                if val == "1개월":
                    st.session_state["ship_start_date"] = today - datetime.timedelta(days=30)
                    st.session_state["ship_end_date"] = today
                elif val == "3개월":
                    st.session_state["ship_start_date"] = today - datetime.timedelta(days=90)
                    st.session_state["ship_end_date"] = today
                elif val == "6개월":
                    st.session_state["ship_start_date"] = today - datetime.timedelta(days=180)
                    st.session_state["ship_end_date"] = today
                elif val == "1년":
                    st.session_state["ship_start_date"] = today - datetime.timedelta(days=365)
                    st.session_state["ship_end_date"] = today

            def on_ship_date_input_change():
                st.session_state["ship_date_radio"] = "직접설정"

            c1, c2, c3 = st.columns([1, 1, 2], vertical_alignment="bottom")
            c1.date_input("시작일", key="ship_start_date", on_change=on_ship_date_input_change)
            c2.date_input("종료일", key="ship_end_date", on_change=on_ship_date_input_change)
            c3.radio("기간 선택", ["1개월", "3개월", "6개월", "1년", "직접설정"], horizontal=True, key="ship_date_radio", on_change=on_ship_date_radio_change, label_visibility="collapsed")
            
            rc1, rc2, rc3, rc4 = st.columns(4)
            f_customer = rc1.text_input("발주처", key="ship_f_cust")
            f_method = rc2.multiselect("배송방법", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"], key="ship_f_method")
            f_carrier = rc3.multiselect("배송업체", shipping_partners, key="ship_f_carrier")
            f_search = rc4.text_input("통합 검색 (제품명/비고)", placeholder="검색어 입력", key="ship_f_search")

        # 데이터 로드 (기간 기준)
        start_dt = datetime.datetime.combine(st.session_state["ship_start_date"], datetime.time.min)
        end_dt = datetime.datetime.combine(st.session_state["ship_end_date"], datetime.time.max)

        # [최적화] 캐싱된 함수를 통해 데이터 로드 (DB 사용량 감소)
        raw_data = load_shipping_orders(start_dt, end_dt)
        rows = []
        for d in raw_data:
            
            # 상태 확인 (출고완료만 필터링)
            if d.get('status') != "출고완료": continue
            
            # [NEW] 메모리 필터링 적용
            if f_customer and f_customer not in d.get('customer', ''): continue
            if f_method and d.get('shipping_method') not in f_method: continue
            if f_carrier and d.get('shipping_carrier') not in f_carrier: continue
            if f_search:
                # 검색 대상 필드 통합
                search_target = f"{d.get('name','')} {d.get('note','')} {d.get('delivery_to','')} {d.get('order_no','')} {d.get('product_code','')}"
                if f_search not in search_target: continue
            
            # [NEW] 운임비 분리 로직 (별도 행 생성) - 상세 내역 우선, 없으면 총액 사용
            ship_cost_lines = d.get('shipping_cost_lines', [])
            ship_cost = d.get('shipping_cost', 0)
            
            if ship_cost_lines:
                # 상세 내역이 있는 경우 (각 항목별로 행 생성)
                for i, line in enumerate(ship_cost_lines):
                    cost_row = d.copy()
                    cost_row['name'] = line.get('name', '운임비')
                    cost_row['product_code'] = ""
                    cost_row['color'] = ""
                    cost_row['size'] = ""
                    cost_row['weight'] = 0
                    cost_row['stock'] = line.get('qty', 1)
                    cost_row['shipping_unit_price'] = line.get('price', 0)
                    cost_row['supply_amount'] = cost_row['stock'] * cost_row['shipping_unit_price']
                    cost_row['shipping_cost'] = 0
                    cost_row['note'] = d.get('shipping_carrier', '')
                    cost_row['id'] = f"{d['id']}_cost_{i}" # 고유 ID (인덱스 포함)
                    rows.append(cost_row)
                
                d['shipping_cost'] = 0 # 원본 행의 운임비는 0으로 설정
            elif ship_cost > 0:
                # 기존 로직 (총액만 있는 경우 - 하위 호환)
                cost_row = d.copy()
                cost_row['name'] = "운임비" # 품명
                cost_row['product_code'] = ""
                cost_row['color'] = ""
                cost_row['size'] = ""
                cost_row['weight'] = 0
                cost_row['stock'] = 1 # 수량 1건
                cost_row['shipping_unit_price'] = ship_cost
                cost_row['supply_amount'] = ship_cost
                cost_row['shipping_cost'] = 0 # 이 행 자체의 운임비 컬럼은 0 (중복 합산 방지)
                cost_row['note'] = d.get('shipping_carrier', '') # 비고에 택배사 등 표시
                cost_row['id'] = f"{d['id']}_cost" # 고유 ID 생성
                rows.append(cost_row)
                
                # 원본 행의 운임비는 0으로 설정 (화면 표시 및 합산 시 중복 방지)
                d['shipping_cost'] = 0

            rows.append(d)
            
        # [수정] 정렬 로직 개선: 날짜 -> 제품/운임비 -> 발주번호 순 (운임비를 날짜별 최하단으로)
        # 날짜 비교 시 분 단위까지만 문자열로 변환하여 비교 (미세한 초 단위 차이 무시)
        rows.sort(key=lambda x: (
            x.get('shipping_date', datetime.datetime.min).strftime('%Y-%m-%d %H:%M') if isinstance(x.get('shipping_date'), datetime.datetime) else str(x.get('shipping_date', '')),
            0 if "_cost" in str(x.get('id', '')) else 1,  # 제품(1) > 운임비(0) => 내림차순(Reverse=True) 시 1(제품)이 먼저 나옴
            x.get('order_no', '')
        ), reverse=True)
        
        if rows:
            df = pd.DataFrame(rows)
            if 'shipping_date' in df.columns:
                df['shipping_date'] = df['shipping_date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)

            # [FIX] 그룹화 및 계산에 필요한 컬럼 존재 여부 확인 및 초기화
            ensure_cols = ['stock', 'shipping_unit_price', 'shipping_cost', 'shipping_method', 'shipping_carrier', 'delivery_to', 'customer', 'name', 'order_no', 'color', 'weight', 'size']
            for c in ensure_cols:
                if c not in df.columns:
                    if c in ['stock', 'shipping_unit_price', 'shipping_cost', 'weight']:
                        df[c] = 0
                    else:
                        df[c] = ""
                elif c in ['stock', 'shipping_unit_price', 'shipping_cost', 'weight']:
                    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
                else:
                    df[c] = df[c].fillna("")

            # [NEW] 공급가액 계산 (단가 * 수량)
            df['supply_amount'] = df.apply(lambda x: int(x.get('stock', 0)) * int(x.get('shipping_unit_price', 0)), axis=1)

            # [NEW] 원본 발주번호(Base Order No) 추출 (예: 2405001-1 -> 2405001)
            # 문자열이 아니거나 '-'가 없으면 그대로 사용
            df['base_order_no'] = df['order_no'].apply(lambda x: str(x).split('-')[0] if isinstance(x, str) else str(x))

            # [NEW] 배송업체 필터링 시 운임비 합계 상단 표시
            if f_carrier:
                total_shipping_cost = df['shipping_cost'].sum()
                carriers_str = ", ".join(f_carrier)
                st.markdown(f"""
                <div style="padding: 10px; background-color: #e3f2fd; border: 1px solid #90caf9; border-radius: 5px; margin-bottom: 10px; color: #1565c0;">
                    <strong>🚚 [{carriers_str}] 운임비 합계: {total_shipping_cost:,}원</strong> (총 {len(df)}건)
                </div>
                """, unsafe_allow_html=True)

            col_map = {
                "shipping_date": "출고일", "customer": "발주처", "order_no": "발주번호", "name": "제품명", "color": "색상", "weight": "중량(g)", "size": "사이즈",
                "stock": "수량", "shipping_method": "배송방법", "shipping_carrier": "배송업체", "shipping_cost": "운임비",
                "stock": "수량", "shipping_unit_price": "단가", "supply_amount": "공급가액",
                "shipping_method": "배송방법", "shipping_carrier": "배송업체", "shipping_cost": "운임비",
                "delivery_to": "납품처", "delivery_contact": "납품연락처", "delivery_address": "납품주소", "note": "비고"
            }
            display_cols = ["shipping_date", "customer", "order_no", "name", "color", "weight", "size", "stock", "shipping_unit_price", "supply_amount", "shipping_method", "shipping_carrier", "shipping_cost", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns]

            # [NEW] 묶어보기 토글
            view_grouped = st.checkbox("동일 출고건 묶어보기 (발주번호 기준)", help="체크하면 분할된 롤들을 원래 발주번호 기준으로 합쳐서 보여줍니다. (단, 출고일, 배송지, 단가가 모두 같아야 합쳐집니다)")
            
            if view_grouped:
                # 그룹화 기준: 원본발주번호 + 출고일 + 거래처 + 배송정보 + 단가
                # (단가가 다르면 합치지 않음, 배송방법이 다르면 합치지 않음)
                group_keys = ['base_order_no', 'shipping_date', 'customer', 'name', 'color', 'weight', 'size', 'shipping_unit_price', 'shipping_method', 'shipping_carrier', 'delivery_to']
                
                # 집계 함수 정의
                agg_funcs = {
                    'stock': 'sum',
                    'supply_amount': 'sum',
                    'shipping_cost': 'sum',
                    'id': list, # ID들을 리스트로 묶음 (취소 처리용)
                    'order_no': lambda x: f"{str(x.iloc[0]).split('-')[0]} (외 {len(x)-1}건)" if len(x) > 1 else str(x.iloc[0]), # 표시용 번호
                    'note': lambda x: ' / '.join(sorted(set([str(s) for s in x if s]))) # 비고 합치기
                }
                # 나머지 컬럼들은 첫 번째 값 사용
                for c in final_cols:
                    if c not in group_keys and c not in agg_funcs:
                        agg_funcs[c] = 'first'

                # 그룹화 실행
                df_display_source = df.groupby(group_keys, as_index=False).agg(agg_funcs)
                
                # 컬럼 순서 재정렬 (final_cols 기준)
                # order_no가 집계되면서 내용이 바뀌었으므로 display용으로 사용
                df_display = df_display_source[final_cols].rename(columns=col_map)
                
                # ID 리스트는 별도 보관 (선택 시 사용)
                df_display_ids = df_display_source['id'].tolist()
                
                st.info(f"💡 묶어보기 모드입니다. 총 **{len(df)}**건의 상세 내역이 **{len(df_display)}**건으로 요약되었습니다.")
            else:
                df_display = df[final_cols].rename(columns=col_map)
                df_display_ids = [[i] for i in df['id'].tolist()] # 1:1 매핑
                st.write(f"총 **{len(df)}**건의 출고 내역이 조회되었습니다.")

            st.write("🔽 목록에서 항목을 선택하여 거래명세서를 발행하거나 취소할 수 있습니다.")
            
            # [수정] 동적 키에 view_mode 반영하여 리셋 방지
            selection = st.dataframe(
                df_display,
                width="stretch",
                on_select="rerun",
                selection_mode="multi-row",
                key=f"ship_done_list_{st.session_state['key_ship_done']}_{view_grouped}"
            )
            
            # [FIX] 목록 선택 변경 시 인쇄 미리보기 초기화 (자동 열림 방지)
            current_selection = selection.selection.rows
            if "last_ship_selection" not in st.session_state:
                st.session_state["last_ship_selection"] = []
            
            if st.session_state["last_ship_selection"] != current_selection:
                keys_to_del = [k for k in st.session_state.keys() if k.startswith("print_view_")]
                for k in keys_to_del: del st.session_state[k]
                st.session_state["last_ship_selection"] = current_selection

            # [NEW] 선택 항목 합계 표시
            if selection.selection.rows:
                sel_indices = selection.selection.rows
                # view_grouped 상태에 따라 참조하는 DF가 다름
                if view_grouped:
                    sel_rows = df_display_source.iloc[sel_indices]
                else:
                    sel_rows = df.iloc[sel_indices]
                    
                sum_qty = sel_rows['stock'].sum()
                sum_amt = sel_rows['supply_amount'].sum()
                sum_cost = sel_rows['shipping_cost'].sum()
                st.info(f"📊 선택 항목 합계: 수량 **{sum_qty:,}** / 공급가액 **{sum_amt:,}원** / 운임비 **{sum_cost:,}원**")
            
            st.divider()
            
            # [NEW] 인쇄 미리보기 초기화 함수 (전역)
            def clear_all_print_views():
                keys_to_del = [k for k in st.session_state.keys() if k.startswith("print_view_")]
                for k in keys_to_del:
                    del st.session_state[k]

            # [NEW] 기능 선택 (버튼식)
            # [FIX] 작업 모드 변경 시 기존 인쇄 미리보기 상태 초기화
            # [MODIFIED] 거래명세서 재발행 옵션 제거 (별도 버튼으로 이동)
            action_mode = st.radio("작업 선택", ["목록 인쇄/엑셀", "출고 취소"], horizontal=True, label_visibility="collapsed", on_change=clear_all_print_views, key="ship_action_mode")
            st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)
            
            # 1. 목록 인쇄 및 엑셀 다운로드
            if action_mode == "목록 인쇄/엑셀":
                st.markdown("##### 현재 조회된 목록 내보내기")
                
                with st.expander("목록 인쇄 옵션"):
                    lp_c1, lp_c2, lp_c3, lp_c4 = st.columns(4)
                    lp_title = lp_c1.text_input("문서 제목", value="출고 목록", key="lp_title")
                    lp_title_size = lp_c2.number_input("제목 크기", value=24, step=1, key="lp_ts")
                    lp_body_size = lp_c3.number_input("본문 크기", value=10, step=1, key="lp_bs")
                    lp_padding = lp_c4.number_input("셀 여백", value=4, step=1, key="lp_pad")
                    
                    lp_c5, lp_c6, lp_c7, lp_c8 = st.columns(4)
                    lp_m_top = lp_c5.number_input("상단 여백", value=15, key="lp_mt")
                    lp_m_bottom = lp_c6.number_input("하단 여백", value=15, key="lp_mb")
                    lp_m_left = lp_c7.number_input("좌측 여백", value=15, key="lp_ml")
                    lp_m_right = lp_c8.number_input("우측 여백", value=15, key="lp_mr")
                    
                    lp_c9, lp_c10 = st.columns(2)
                    lp_bo = lp_c9.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="lp_bo")
                    lp_bi = lp_c10.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="lp_bi")

                    lp_exclude_cols = st.multiselect("인쇄 제외 컬럼", list(col_map.values()), key="lp_exclude")

                lc1, lc2 = st.columns([1, 1])
                
                # 엑셀 다운로드
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    # [FIX] 화면에 보이는 그대로(그룹화 여부 반영) 엑셀 다운로드
                    df_display.to_excel(writer, index=False)
                lc1.download_button("💾 엑셀 다운로드", buffer.getvalue(), f"출고목록_{today}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
                # 목록 인쇄
                if lc2.button("🖨️ 인쇄하기"):
                    print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    # [수정] 선택된 항목이 있으면 해당 항목만, 없으면 전체 목록 인쇄
                    if selection.selection.rows:
                        target_df = df_display.iloc[selection.selection.rows] # 화면에 보이는 그대로 인쇄
                        print_title = f"{lp_title} (선택 항목)"
                    else:
                        target_df = df_display # 화면에 보이는 그대로 인쇄
                        print_title = lp_title

                    # 합계 계산
                    total_qty = target_df['stock'].sum() if 'stock' in target_df.columns else 0
                    total_amt = target_df['supply_amount'].sum() if 'supply_amount' in target_df.columns else 0
                    total_cost = target_df['shipping_cost'].sum() if 'shipping_cost' in target_df.columns else 0
                    
                    print_df = target_df # 이미 컬럼명 변경됨
                    
                    # 제외 컬럼 필터링
                    if lp_exclude_cols:
                        print_df = print_df.drop(columns=[c for c in lp_exclude_cols if c in print_df.columns])
                    
                    html = f"""
                    <html>
                    <head>
                        <title>{lp_title}</title>
                        <style>
                            @page {{ margin: {lp_m_top}mm 15mm {lp_m_bottom}mm 15mm; }}
                            @page {{ margin: {lp_m_top}mm {lp_m_right}mm {lp_m_bottom}mm {lp_m_left}mm; }}
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                            h2 {{ text-align: center; margin-bottom: 5px; font-size: {lp_title_size}px; }}
                            .info {{ text-align: right; font-size: 10px; margin-bottom: 10px; color: #555; }}
                            table {{ width: 100%; border-collapse: collapse; font-size: {lp_body_size}px; margin-bottom: 10px; border: {lp_bo}px solid #444; }}
                            th, td {{ border: {lp_bi}px solid #444; padding: {lp_padding}px; text-align: center; }}
                            th {{ background-color: #f0f0f0; }}
                            .summary {{ text-align: right; font-weight: bold; font-size: {lp_body_size + 2}px; margin-top: 10px; border-top: 2px solid #444; padding-top: 5px; }}
                            @media screen {{ body {{ display: none; }} }}
                        </style>
                    </head>
                    <body onload="window.print()">
                        <h2>{lp_title}</h2>
                        <div class="info">출력일시: {print_now}</div>
                        {print_df.to_html(index=False)}
                        <div class="summary">
                            합계 - 수량: {total_qty:,} / 공급가액: {total_amt:,}원 / 운임비: {total_cost:,}원
                        </div>
                    </body>
                    </html>
                    """
                    st.components.v1.html(html, height=0, width=0)

            # 3. 출고 취소 (기존 로직 이동)
            elif action_mode == "출고 취소":
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    
                    # [수정] 취소 대상 ID 목록 확보
                    target_ids = []
                    if view_grouped:
                        # 그룹화된 행의 'id' 컬럼은 리스트 형태임
                        sel_rows = df_display_source.iloc[selected_indices]
                        for ids in sel_rows['id']:
                            target_ids.extend(ids)
                    else:
                        sel_rows = df.iloc[selected_indices]
                        target_ids = sel_rows['id'].tolist()
                    
                    if st.button(f"선택 항목 출고 취소 ({len(target_ids)}건)", type="primary"):
                        # [수정] 개별 업데이트 대신 Batch Write 사용 (성능 및 안정성 개선)
                        # [NEW] 부분 출고 취소 시 재고 병합 로직 추가
                        progress_text = "출고 취소 처리 중..."
                        my_bar = st.progress(0, text=progress_text)

                        batch = db.batch()
                        batch_count = 0
                        processed_count = 0

                        for doc_id in target_ids:
                            # [FIX] 가상 운임비 행(_cost 포함)은 실제 문서가 아니므로 건너뜀 (404 오류 방지)
                            if "_cost" in doc_id:
                                continue
                                
                            doc_ref = db.collection("orders").document(doc_id)
                            doc_snap = doc_ref.get()
                            
                            if not doc_snap.exists:
                                continue

                            doc_data = doc_snap.to_dict()
                            parent_id = doc_data.get('parent_id')
                            stock_to_return = int(doc_data.get('stock', 0))
                            
                            merged = False
                            if parent_id:
                                parent_ref = db.collection("orders").document(parent_id)
                                parent_snap = parent_ref.get()
                                
                                # 부모 문서가 존재하고, 현재 '봉제완료' 상태(재고 상태)라면 병합
                                if parent_snap.exists:
                                    parent_data = parent_snap.to_dict()
                                    if parent_data.get('status') == "봉제완료":
                                        # 부모 문서에 수량 더하기
                                        batch.update(parent_ref, {"stock": firestore.Increment(stock_to_return)})
                                        # 현재 문서 삭제
                                        batch.delete(doc_ref)
                                        merged = True
                            
                            if not merged:
                                # 병합되지 않으면 상태만 변경 (출고 정보 초기화 포함)
                                updates = {
                                    "status": "봉제완료",
                                    "shipping_date": firestore.DELETE_FIELD,
                                    "shipping_method": firestore.DELETE_FIELD,
                                    "shipping_carrier": firestore.DELETE_FIELD,
                                    "shipping_cost": firestore.DELETE_FIELD,
                                    "shipping_cost_lines": firestore.DELETE_FIELD,
                                    "delivery_to": firestore.DELETE_FIELD,
                                    "delivery_contact": firestore.DELETE_FIELD,
                                    "delivery_address": firestore.DELETE_FIELD
                                }
                                batch.update(doc_ref, updates)
                            
                            batch_count += 1
                            processed_count += 1
                            my_bar.progress(processed_count / len(target_ids), text=f"처리 중... ({processed_count}/{len(target_ids)})")

                            if batch_count >= 400:
                                batch.commit()
                                batch = db.batch()
                                batch_count = 0
                        
                        if batch_count > 0:
                            batch.commit()
                        
                        my_bar.empty()
                        st.success(f"총 {len(target_ids)}건의 출고가 취소되었습니다.")

                        # [FIX] 데이터 캐시를 지워 목록이 즉시 갱신되도록 함
                        load_shipping_orders.clear()
                        
                        # [FIX] 취소 후 목록 갱신 및 선택 초기화
                        st.session_state["key_ship_done"] += 1
                        if "last_ship_selection" in st.session_state:
                            del st.session_state["last_ship_selection"]
                        st.rerun()
                else:
                    st.info("취소할 항목을 선택하세요.")

            # [NEW] 거래명세서 확인 버튼 (하단 별도 배치)
            st.divider()
            c_inv_btn, _ = st.columns([2, 8])
            if c_inv_btn.button("📄 거래명세서 확인하기"):
                if selection.selection.rows:
                    st.session_state["show_invoice_view_status"] = True
                else:
                    st.warning("거래명세서를 확인할 항목을 선택하세요.")
            
            if st.session_state.get("show_invoice_view_status"):
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    if view_grouped:
                        sel_rows = df_display_source.iloc[selected_indices]
                    else:
                        sel_rows = df.iloc[selected_indices]
                    
                    st.markdown("---")
                    st.markdown("#### 📄 거래명세서 확인")
                    render_invoice_ui(db, sel_rows)
                    
                    if st.button("닫기", key="close_inv_view"):
                        st.session_state["show_invoice_view_status"] = False
                        st.rerun()
                else:
                    st.session_state["show_invoice_view_status"] = False
                    st.rerun()

        else:
            st.info("출고 완료된 내역이 없습니다.")

    elif sub_menu == "배송내역":
        st.subheader("📊 배송/운임 통계")
        st.info("기간별, 배송업체별 운임비 지출 현황을 확인합니다.")
        
        with st.form("ship_stats_form"):
            # [수정] 통계 기준 선택 (기간별/월별/년도별)
            stat_type = st.radio("통계 기준", ["기간별(일자)", "월별", "년도별"], horizontal=True)
            
            c1, c2, c3 = st.columns(3)
            
            if stat_type == "기간별(일자)":
                today = datetime.date.today()
                stats_date = c1.date_input("조회 기간", [today - datetime.timedelta(days=30), today])
            elif stat_type == "월별":
                this_year = datetime.date.today().year
                stats_year = c1.number_input("조회 년도", value=this_year, step=1, format="%d")
            else: # 년도별
                c1.write("최근 데이터 기준")

            stats_carrier = c2.selectbox("배송업체", ["전체"] + shipping_partners)
            stats_customer = c3.text_input("발주처")
            
            submitted = st.form_submit_button("조회")
            
        if submitted:
        # 데이터 조회 및 필터링
            docs = db.collection("orders").where("status", "==", "출고완료").stream()
            rows = []
            for doc in docs:
                d = doc.to_dict()
                s_date = d.get('shipping_date')
                
                if s_date:
                    if s_date.tzinfo: s_date = s_date.replace(tzinfo=None)
                    
                    # 날짜 필터링
                    if stat_type == "기간별(일자)" and isinstance(stats_date, list) and len(stats_date) == 2:
                        start_dt = datetime.datetime.combine(stats_date[0], datetime.time.min)
                        end_dt = datetime.datetime.combine(stats_date[1], datetime.time.max)
                        if start_dt <= s_date <= end_dt:
                            rows.append(d)
                    elif stat_type == "월별":
                        if s_date.year == stats_year:
                            rows.append(d)
                    else: # 년도별 (전체)
                        rows.append(d)

            if rows:
                df_stats = pd.DataFrame(rows)
                # 운임비 합계
                total_cost = df_stats['shipping_cost'].sum() if 'shipping_cost' in df_stats.columns else 0
                total_count = len(df_stats)
                
                st.metric("총 운임비 지출", f"{total_cost:,}원", f"총 {total_count}건")

                # 추가 필터링 (업체/거래처) - 메모리 상에서 처리
                if stats_carrier != "전체":
                    df_stats = df_stats[df_stats['shipping_carrier'] == stats_carrier]
                if stats_customer:
                    df_stats = df_stats[df_stats['customer'].str.contains(stats_customer, na=False)]
                
                st.divider()
                
                # 통계 그룹화 기준 설정
                if stat_type == "기간별(일자)":
                    df_stats['group_key'] = df_stats['shipping_date'].apply(lambda x: x.strftime('%Y-%m-%d'))
                    group_label = "일자"
                elif stat_type == "월별":
                    df_stats['group_key'] = df_stats['shipping_date'].apply(lambda x: x.strftime('%Y-%m'))
                    group_label = "월"
                else:
                    df_stats['group_key'] = df_stats['shipping_date'].apply(lambda x: x.strftime('%Y'))
                    group_label = "년도"

                c_chart1, c_chart2 = st.columns(2)
                
                # 1. 시계열 추이 (운임비)
                with c_chart1:
                    st.markdown(f"##### {group_label}별 운임비 추이")
                    time_stats = df_stats.groupby('group_key')['shipping_cost'].sum().reset_index()
                    time_stats.columns = [group_label, '운임비']
                    st.bar_chart(time_stats.set_index(group_label))

                # 2. 배송업체별 점유율
                with c_chart2:
                    st.markdown("##### 배송업체별 운임비 비중")
                    if 'shipping_carrier' in df_stats.columns:
                        carrier_pie = df_stats.groupby('shipping_carrier')['shipping_cost'].sum()
                        st.bar_chart(carrier_pie) # Streamlit 기본 차트 사용

                # 3. 상세 테이블 (업체별)
                if 'shipping_carrier' in df_stats.columns and 'shipping_cost' in df_stats.columns:
                    st.markdown("##### 업체별 상세 지출 현황")
                    carrier_stats = df_stats.groupby(['shipping_carrier', 'customer'])['shipping_cost'].sum().reset_index()
                    # [수정] 컬럼 수 불일치 오류 해결 (3개 컬럼)
                    carrier_stats.columns = ['배송업체', '발주처', '운임비 합계']
                    carrier_stats = carrier_stats.sort_values('운임비 합계', ascending=False)
                    st.dataframe(carrier_stats, width="stretch", hide_index=True)
                    
                    st.bar_chart(carrier_stats.set_index('배송업체'))
            else:
                st.info("조회된 배송 내역이 없습니다.")
        else:
            st.write("👆 위 조건 설정 후 **조회** 버튼을 누르면 결과가 표시됩니다.")

# [NEW] 거래명세서 발행 UI 및 로직 함수 (공통 사용)
def render_invoice_ui(db, df_rows):
    user_id = st.session_state.get("user_id")
    
    # [FIX] 세션 상태 초기화 (출고 작업에서 바로 호출될 경우를 대비하여 설정값이 없으면 로드)
    if "stmt_settings" not in st.session_state:
        comp_doc = db.collection("settings").document("company_info").get()
        comp_info = comp_doc.to_dict() if comp_doc.exists else {}
        
        default_settings = {
            "opt_type": "공급받는자용", "opt_merge": True, "opt_inc_ship": True,
            "opt_show_sign": True, "opt_hide_price": False, "opt_show_logo": True,
            "opt_logo_height": 50, "opt_show_stamp": True, "opt_sw": 50, "opt_st": -10, "opt_sr": 0,
            "opt_show_appr": False, "opt_ac": 3,
            "opt_at_0": "담당", "opt_at_1": "검토", "opt_at_2": "승인", "opt_at_3": "이사", "opt_at_4": "사장",
            "bo": 1.0, "bi": 0.5, "tb": 1.0,
            "mt": 10, "mb": 10, "ml": 10, "mr": 10,
            "title": "거 래 명 세 서", "ts": 24, "fs": 12, "pad": 5,
            "rows": 18,
            "w_date": 5, "w_item": 25, "w_spec": 15, "w_qty": 8,
            "w_price": 10, "w_supply": 12, "w_tax": 10, "w_note": 15,
            "opt_bank": True, "opt_vat_chk": False,
            "opt_note": comp_info.get('note', '')
        }
        st.session_state["stmt_settings"] = load_user_settings(user_id, "stmt_settings", default_settings)

    # [NEW] 설정 업데이트 콜백
    def update_stmt_setting(key):
        st.session_state["stmt_settings"][key] = st.session_state[f"w_stmt_{key}"]
        save_user_settings(user_id, "stmt_settings", st.session_state["stmt_settings"]) # [NEW] DB 저장
        # 미리보기 초기화는 필요 시 추가

    # [NEW] 거래명세서 상세 설정
    with st.expander("⚙️ 거래명세서 상세 설정", expanded=False):
        st.info("인쇄 모양과 내용을 설정합니다. (모든 거래처에 공통 적용)")
        s = st.session_state["stmt_settings"]
        
        t_c1, t_c2, t_c3 = st.columns(3)
        opt_type_options = ["공급받는자용", "공급자용", "모두 인쇄(2장)", "표시 없음"]
        t_c1.radio("인쇄 종류", opt_type_options, index=opt_type_options.index(s['opt_type']), key="w_stmt_opt_type", on_change=update_stmt_setting, args=('opt_type',))
        t_c2.checkbox("동일 품목 합산 발행", value=s['opt_merge'], help="제품명, 규격, 단가가 같은 항목을 한 줄로 합쳐서 표시합니다.", key="w_stmt_opt_merge", on_change=update_stmt_setting, args=('opt_merge',))
        t_c3.checkbox("운임비 포함하여 발행", value=s['opt_inc_ship'], key="w_stmt_opt_inc_ship", on_change=update_stmt_setting, args=('opt_inc_ship',))
        
        st.markdown("---")
        st.markdown("###### 표시 설정")
        r1_c1, r1_c2, r1_c3, r1_c4 = st.columns([1.5, 2.0, 1.5, 1.5])
        r1_c1.checkbox("인수자 서명란", value=s['opt_show_sign'], key="w_stmt_opt_show_sign", on_change=update_stmt_setting, args=('opt_show_sign',))
        r1_c2.checkbox("단가/금액 숨기기", value=s['opt_hide_price'], key="w_stmt_opt_hide_price", on_change=update_stmt_setting, args=('opt_hide_price',))
        r1_c3.checkbox("회사 로고 표시", value=s['opt_show_logo'], key="w_stmt_opt_show_logo", on_change=update_stmt_setting, args=('opt_show_logo',))
        
        if s['opt_show_logo']:
            r1_c4.number_input("로고 높이(px)", value=s['opt_logo_height'], min_value=20, max_value=150, step=5, key="w_stmt_opt_logo_height", on_change=update_stmt_setting, args=('opt_logo_height',))
        
        r2_c1, r2_c2, r2_c3, r2_c4 = st.columns([1.5, 1.5, 1.5, 1.5])
        r2_c1.checkbox("직인(도장) 표시", value=s['opt_show_stamp'], key="w_stmt_opt_show_stamp", on_change=update_stmt_setting, args=('opt_show_stamp',))
        
        if s['opt_show_stamp']:
            r2_c2.number_input("직인 너비(px)", value=s['opt_sw'], step=5, key="w_stmt_opt_sw", on_change=update_stmt_setting, args=('opt_sw',))
            r2_c3.number_input("상단 위치(px)", value=s['opt_st'], step=5, help="음수면 위로, 양수면 아래로 이동", key="w_stmt_opt_st", on_change=update_stmt_setting, args=('opt_st',))
            r2_c4.number_input("우측 위치(px)", value=s['opt_sr'], step=5, help="양수면 왼쪽으로 이동", key="w_stmt_opt_sr", on_change=update_stmt_setting, args=('opt_sr',))

        st.checkbox("결재란 표시", value=s['opt_show_appr'], key="w_stmt_opt_show_appr", on_change=update_stmt_setting, args=('opt_show_appr',))
        
        if s['opt_show_appr']:
            st.caption("결재란 설정")
            c_a1, c_a2 = st.columns([1, 3])
            c_a1.number_input("결재 인원", min_value=1, max_value=5, value=s['opt_ac'], key="w_stmt_opt_ac", on_change=update_stmt_setting, args=('opt_ac',))
            
            c_titles = st.columns(s['opt_ac'])
            for j in range(s['opt_ac']):
                c_titles[j].text_input(f"직책 {j+1}", value=s.get(f"opt_at_{j}", ""), key=f"w_stmt_opt_at_{j}", on_change=update_stmt_setting, args=(f'opt_at_{j}',))

        st.markdown("---")
        st.markdown("###### 테두리 및 스타일")
        b_c1, b_c2, b_c3 = st.columns(3)
        b_c1.number_input("외곽선 굵기(px)", value=s['bo'], step=0.5, key="w_stmt_bo", on_change=update_stmt_setting, args=('bo',))
        b_c2.number_input("내부선 굵기(px)", value=s['bi'], step=0.5, key="w_stmt_bi", on_change=update_stmt_setting, args=('bi',))
        b_c3.number_input("상단박스 선굵기(px)", value=s['tb'], step=0.5, key="w_stmt_tb", on_change=update_stmt_setting, args=('tb',))
        
        m_c1, m_c2, m_c3, m_c4 = st.columns(4)
        m_c1.number_input("상단 여백(mm)", value=s['mt'], key="w_stmt_mt", on_change=update_stmt_setting, args=('mt',))
        m_c2.number_input("하단 여백(mm)", value=s['mb'], key="w_stmt_mb", on_change=update_stmt_setting, args=('mb',))
        m_c3.number_input("좌측 여백(mm)", value=s['ml'], key="w_stmt_ml", on_change=update_stmt_setting, args=('ml',))
        m_c4.number_input("우측 여백(mm)", value=s['mr'], key="w_stmt_mr", on_change=update_stmt_setting, args=('mr',))
        
        s_c1, s_c2, s_c3, s_c4 = st.columns(4)
        s_c1.text_input("문서 제목", value=s['title'], key="w_stmt_title", on_change=update_stmt_setting, args=('title',))
        s_c2.number_input("제목 크기(px)", value=s['ts'], key="w_stmt_ts", on_change=update_stmt_setting, args=('ts',))
        s_c3.number_input("본문 글자 크기(px)", value=s['fs'], key="w_stmt_fs", on_change=update_stmt_setting, args=('fs',))
        s_c4.number_input("셀 여백(px)", value=s['pad'], key="w_stmt_pad", on_change=update_stmt_setting, args=('pad',))
        
        st.number_input("목록 최소 줄 수 (A4 맞춤용)", min_value=5, max_value=50, value=s['rows'], help="용지 여백에 따라 줄 수를 조절하여 A4 한 페이지에 맞추세요.", key="w_stmt_rows", on_change=update_stmt_setting, args=('rows',))
        
        st.markdown("---")
        st.markdown("###### 컬럼 너비 설정 (%)")
        wc1, wc2, wc3, wc4 = st.columns(4)
        wc1.number_input("월일", value=s['w_date'], step=1, key="w_stmt_w_date", on_change=update_stmt_setting, args=('w_date',))
        wc2.number_input("품목", value=s['w_item'], step=1, key="w_stmt_w_item", on_change=update_stmt_setting, args=('w_item',))
        wc3.number_input("규격", value=s['w_spec'], step=1, key="w_stmt_w_spec", on_change=update_stmt_setting, args=('w_spec',))
        wc4.number_input("수량", value=s['w_qty'], step=1, key="w_stmt_w_qty", on_change=update_stmt_setting, args=('w_qty',))
        
        wc5, wc6, wc7, wc8 = st.columns(4)
        wc5.number_input("단가", value=s['w_price'], step=1, key="w_stmt_w_price", on_change=update_stmt_setting, args=('w_price',))
        wc6.number_input("공급가액", value=s['w_supply'], step=1, key="w_stmt_w_supply", on_change=update_stmt_setting, args=('w_supply',))
        wc7.number_input("세액", value=s['w_tax'], step=1, key="w_stmt_w_tax", on_change=update_stmt_setting, args=('w_tax',))
        wc8.number_input("비고", value=s['w_note'], step=1, key="w_stmt_w_note", on_change=update_stmt_setting, args=('w_note',))
        
        # [NEW] 너비 합계 검증 및 안내
        current_total_width = s['w_date'] + s['w_item'] + s['w_spec'] + s['w_qty'] + s['w_note']
        if not s['opt_hide_price']:
            current_total_width += s['w_price'] + s['w_supply'] + s['w_tax']
        
        if current_total_width != 100:
            diff = 100 - current_total_width
            msg = "부족합니다" if diff > 0 else "초과했습니다"
            st.warning(f"⚠️ 현재 너비 합계: {current_total_width}% ({abs(diff)}% {msg})")
        else:
            st.success("✅ 너비 합계: 100%")

        st.markdown("---")
        st.markdown("###### 하단 문구")
        st.checkbox("입금계좌 표시", value=s['opt_bank'], key="w_stmt_opt_bank", on_change=update_stmt_setting, args=('opt_bank',))
        
        def on_vat_note_change():
            if st.session_state.get("w_stmt_opt_vat_chk"):
                current_note = st.session_state["stmt_settings"].get("opt_note", "")
                if "(부가세 포함)" not in current_note:
                    st.session_state["stmt_settings"]["opt_note"] = (current_note + " (부가세 포함)").strip()
            st.session_state["stmt_settings"]["opt_vat_chk"] = st.session_state["w_stmt_opt_vat_chk"]
            save_user_settings(user_id, "stmt_settings", st.session_state["stmt_settings"]) # [NEW] DB 저장

        st.checkbox("부가세 포함 문구 추가", value=s['opt_vat_chk'], key="w_stmt_opt_vat_chk", on_change=on_vat_note_change)
        st.text_area("하단 참고사항", value=s['opt_note'], height=60, key="w_stmt_opt_note", on_change=update_stmt_setting, args=('opt_note',))

    # 회사 정보 가져오기
    comp_doc = db.collection("settings").document("company_info").get()
    comp_info = comp_doc.to_dict() if comp_doc.exists else {}
    
    partners_map = get_partners_map()

    if 'customer' not in df_rows.columns:
        st.error("거래처 정보가 없어 명세서를 발행할 수 없습니다.")
    else:
        # [최적화] 그룹화 및 정렬 (탭 순서 고정)
        grouped = df_rows.groupby('customer', sort=True)
        groups_data = [(name, group) for name, group in grouped]
        
        if len(groups_data) > 20:
            st.warning(f"⚠️ 선택된 거래처가 {len(groups_data)}곳입니다. 탭이 많아 화면이 느려질 수 있습니다.")

        tabs = st.tabs([g[0] for g in groups_data])
        
        for i, (cust_name, group_df) in enumerate(groups_data):
            with tabs[i]:
                st.markdown(f"### 📄 {cust_name} 거래명세서")
                
                partner_info = partners_map.get(cust_name, {})
                
                # [NEW] 설정값 로드 (전역 설정 사용)
                s = st.session_state["stmt_settings"]
                appr_titles = []
                if s['opt_show_appr']:
                    for j in range(s['opt_ac']):
                        appr_titles.append(s.get(f"opt_at_{j}", ""))

                # [수정] 키(Key)에 인덱스 대신 거래처명을 사용하여 데이터 꼬임 방지
                with st.form(f"stmt_form_{cust_name}"):
                    c1, c2 = st.columns(2)
                    stmt_date = c1.date_input("작성일자", datetime.date.today(), key=f"sd_{cust_name}")
                    stmt_no = c2.text_input("일련번호", value=datetime.datetime.now().strftime("%y%m%d-") + str(i+1).zfill(2), key=f"sn_{cust_name}")
                    
                    with st.expander("공급자/공급받는자 정보 수정", expanded=False):
                        sc1, sc2 = st.columns(2)
                        sc1.markdown("###### [공급자]") # 키 충돌 방지를 위해 키값 변경
                        s_name = sc1.text_input("상호", value=comp_info.get('name', ''), key=f"s_nm_{cust_name}")
                        s_rep = sc1.text_input("대표자", value=comp_info.get('rep_name', ''), key=f"s_rep_{cust_name}")
                        s_biz = sc1.text_input("등록번호", value=comp_info.get('biz_num', ''), key=f"s_biz_{cust_name}")
                        s_addr = sc1.text_input("주소", value=f"{comp_info.get('address', '')} {comp_info.get('address_detail', '')}", key=f"s_addr_{cust_name}")
                        s_cond = sc1.text_input("업태", value=comp_info.get('biz_type', ''), key=f"s_cond_{cust_name}")
                        s_item = sc1.text_input("종목", value=comp_info.get('biz_item', ''), key=f"s_item_{cust_name}")
                        
                        sc2.markdown("###### [공급받는자]")
                        r_name = sc2.text_input("상호(받는분)", value=cust_name, key=f"r_nm_{cust_name}")
                        r_rep = sc2.text_input("대표자(받는분)", value=partner_info.get('rep_name', ''), key=f"r_rep_{cust_name}")
                        r_biz = sc2.text_input("등록번호(받는분)", value=partner_info.get('biz_num', ''), key=f"r_biz_{cust_name}")
                        r_addr = sc2.text_input("주소(받는분)", value=f"{partner_info.get('address', '')} {partner_info.get('address_detail', '')}", key=f"r_addr_{cust_name}")

                    items = []
                    for _, row in group_df.iterrows():
                        # [FIX] 'Timestamp' object is not subscriptable 오류 수정
                        shipping_date_obj = row.get('shipping_date')
                        shipping_date_str = shipping_date_obj.strftime('%m-%d') if shipping_date_obj and hasattr(shipping_date_obj, 'strftime') else ""
                        spec = f"{row.get('size', '')} {row.get('color', '')}".strip()
                        qty = int(row.get('stock', 0))
                        u_price = int(row.get('shipping_unit_price', 0))
                        amt = int(row.get('supply_amount', 0))
                        
                        # [FIX] 부가세 포함 여부에 따른 세액 계산
                        is_vat_inc = row.get('vat_included', False)
                        if is_vat_inc:
                            # 부가세 포함 시: 단가/금액에 포함됨, 세액란은 0 (또는 별도 표기 안함)
                            tax = 0
                        else:
                            tax = int(amt * 0.1) # 별도 시 10%
                        
                        items.append({
                            "월일": shipping_date_str,
                            "품목": row.get('name', ''),
                            "규격": spec,
                            "수량": qty,
                            "단가": u_price,
                            "공급가액": amt,
                            "세액": tax,
                            "비고": row.get('note', '')
                        })
                        
                        cost = int(row.get('shipping_cost', 0))
                        if cost > 0 and s['opt_inc_ship']:
                            items.append({
                                "월일": shipping_date_str,
                                "품목": "운임비",
                                "규격": "",
                                "수량": 1,
                                "단가": cost,
                                "공급가액": cost,
                                "세액": int(cost * 0.1),
                                "비고": row.get('shipping_carrier', '')
                            })

                    # [NEW] 동일 품목 합산 로직
                    if s['opt_merge']:
                        df_items = pd.DataFrame(items)
                        if not df_items.empty:
                            # 그룹화 기준: 품목, 규격, 단가
                            # 월일과 비고는 첫 번째 값 또는 병합
                            grouped_items = df_items.groupby(['품목', '규격', '단가'], as_index=False).agg({
                                '수량': 'sum',
                                '공급가액': 'sum',
                                '세액': 'sum',
                                '월일': 'first',
                                '비고': lambda x: ' / '.join(sorted(set([str(v) for v in x if v])))
                            })
                            items = grouped_items.to_dict('records')

                    st.write("품목 내역 (수정 가능)")
                    # [FIX] 리스트를 DataFrame으로 변환하여 hide_index가 확실히 적용되도록 함
                    edited_items = st.data_editor(pd.DataFrame(items), num_rows="dynamic", hide_index=True, key=f"items_{cust_name}", use_container_width=True)
                    
                    # [FIX] DataFrame 집계 함수 사용 (TypeError 해결)
                    total_supply = int(edited_items['공급가액'].sum())
                    total_tax = int(edited_items['세액'].sum())
                    grand_total = total_supply + total_tax
                    
                    st.info(f"합계: 공급가액 {total_supply:,} + 세액 {total_tax:,} = 총액 {grand_total:,}")
                    
                    if st.form_submit_button("🖨️ 거래명세서 발행"):
                        # [FIX] DataFrame을 딕셔너리 리스트로 변환 (템플릿 렌더링용)
                        print_items_list = edited_items.to_dict('records')
                        
                        stamp_b64 = comp_info.get('stamp_img') if s['opt_show_stamp'] else None
                        stamp_html = f"<img src='data:image/png;base64,{stamp_b64}' class='stamp'>" if stamp_b64 else ""
                        logo_b64 = comp_info.get('logo_img') if s['opt_show_logo'] else None
                        logo_html = f"<img src='data:image/png;base64,{logo_b64}' class='logo'>" if logo_b64 else ""
                        
                        # 결재란 HTML
                        appr_html = ""
                        if s['opt_show_appr']:
                            # [수정] 동적 결재란 생성
                            appr_html = '<table class="appr-table"><tr><td rowspan="2" class="appr-header">결<br>재</td>'
                            for t in appr_titles: # 위에서 로드한 titles 사용
                                appr_html += f'<td>{t}</td>'
                            appr_html += '</tr><tr>'
                            for _ in range(s['opt_ac']):
                                appr_html += '<td class="appr-box"></td>'
                            appr_html += '</tr></table>'
                        
                        # 인수자 서명란 HTML
                        sign_html = ""
                        if s['opt_show_sign']:
                            sign_html = "<div style='margin-top:5px; text-align:right;'><strong>인수자 : ________________ (인)</strong></div>"

                        # 은행 정보
                        bank_info = f"입금계좌: {comp_info.get('bank_name','')} {comp_info.get('bank_account','')}" if s['opt_bank'] else ""

                        html_template = f"""
                        <html>
                        <head>
                            <style>
                                * {{ box-sizing: border-box; }}
                                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
                                .container {{ width: 100%; margin: 0 auto; }}
                                .header {{ 
                                    text-align: center; 
                                    font-size: {s['ts']}px; 
                                    font-weight: bold; 
                                    text-decoration: underline; 
                                    margin-bottom: 10px; 
                                    position: relative;
                                    min-height: {s['opt_logo_height'] + 10}px; /* 로고 높이만큼 공간 확보 */
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                }}
                                .logo {{ position: absolute; left: 0; top: 50%; transform: translateY(-50%); max-height: {s['opt_logo_height']}px; }}
                                .top-section {{ display: flex; width: 100%; border: {s['tb']}px solid #333; margin-bottom: 5px; }}
                                .supplier, .recipient {{ flex: 1; padding: 5px; }}
                                .supplier {{ border-left: {s['bi']}px solid #333; }}
                                .row {{ display: flex; margin-bottom: 2px; }}
                                .label {{ width: 90px; text-align: center; background: transparent; border: {s['bi']}px solid #ccc; font-size: 12px; display: flex; align-items: center; justify-content: center; }}
                                .value {{ flex: 1; padding-left: 5px; border-bottom: 1px solid #ccc; font-size: 12px; }}
                                .stamp-box {{ position: relative; }}
                                .stamp {{ position: absolute; right: {s['opt_sr']}px; top: {s['opt_st']}px; width: {s['opt_sw']}px; opacity: 0.8; }}
                                .main-table {{ width: 100%; border-collapse: collapse; border: {s['bo']}px solid #333; font-size: {s['fs']}px; }}
                                .main-table th {{ background: #eee; border: {s['bi']}px solid #333; padding: {s['pad']}px; text-align: center; }}
                                .main-table td {{ border: {s['bi']}px solid #333; padding: {s['pad']}px; }}
                                .center {{ text-align: center; }}
                                .right {{ text-align: right; }}
                                .total-row {{ background: #f9f9f9; font-weight: bold; }}
                                .total-amount-section {{ border: {s['bo']}px solid #333; border-bottom: none; padding: 8px; text-align: center; font-weight: bold; font-size: 1.1em; background-color: #f9f9f9; }}
                                .appr-table {{ float: right; border-collapse: collapse; font-size: 10px; margin-bottom: 5px; }}
                                .appr-table td {{ border: 1px solid #333; text-align: center; padding: 2px; }}
                                .appr-header {{ width: 20px; background: #eee; }}
                                .appr-box {{ width: 50px; height: 40px; }}
                                @media print {{ 
                                    @page {{ size: A4; margin: {s['mt']}mm {s['mr']}mm {s['mb']}mm {s['ml']}mm; }} 
                                    body {{ padding: 0; -webkit-print-color-adjust: exact; }} 
                                    .page-break {{ page-break-before: always; }}
                                }}
                            </style>
                        </head>
                        <body onload="window.print()">
                    """
                    
                        # 페이지 생성 함수 (공급자용/공급받는자용)
                        def create_page(title_suffix, is_supplier_copy):
                            # [NEW] 단가/금액 숨김 여부에 따른 헤더 처리
                            price_header = f'<th width="{s["w_price"]}%">단가</th><th width="{s["w_supply"]}%">공급가액</th><th width="{s["w_tax"]}%">세액</th>' if not s['opt_hide_price'] else ''
                            
                            # [NEW] 합계 금액 한글 변환
                            korean_grand_total = num_to_korean(grand_total)
                            total_amount_html = f"""
                            <div class="total-amount-section">
                                합계금액 (공급가액+세액): 일금 {korean_grand_total} 원정 (₩ {grand_total:,})
                            </div>
                            """
                            
                            page_html = f"""
                                <div class="container">
                                    <div class="header">
                                        {logo_html} {s['title']}
                                        <span style="font-size: 12px; position: absolute; right: 0; bottom: 0; text-decoration: none; font-weight:normal;">(No. {stmt_no})</span>
                                    </div>
                                    {appr_html}
                                    <div style="clear:both;"></div>
                                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 12px;">
                                        <span style="font-weight: bold;">{f"({title_suffix})" if title_suffix else ""}</span>
                                        <span>작성일자: {stmt_date.strftime('%Y년 %m월 %d일')}</span>
                                    </div>
                                    <div class="top-section">
                                        <div class="recipient">
                                            <div style="text-align: center; font-weight: normal; margin-bottom: 5px; border-bottom: {s['bi']}px solid #333; padding-bottom: 2px;">[공급받는자]</div>
                                            <div class="row"><div class="label">상호</div><div class="value">{r_name}</div></div>
                                            <div class="row"><div class="label">사업자번호</div><div class="value">{r_biz}</div></div>
                                            <div class="row"><div class="label">대표자</div><div class="value">{r_rep}</div></div>
                                            <div class="row"><div class="label">주소</div><div class="value">{r_addr}</div></div>
                                        </div>
                                        <div class="supplier">
                                            <div style="text-align: center; font-weight: normal; margin-bottom: 5px; border-bottom: {s['bi']}px solid #333; padding-bottom: 2px;">[공급자]</div>
                                            <div class="row"><div class="label">상호</div><div class="value stamp-box">{s_name} {stamp_html}</div></div>
                                            <div class="row"><div class="label">사업자번호</div><div class="value">{s_biz}</div></div>
                                            <div class="row"><div class="label">대표자</div><div class="value">{s_rep}</div></div>
                                            <div class="row"><div class="label">주소</div><div class="value">{s_addr}</div></div>
                                            <div class="row"><div class="label">업태</div><div class="value">{s_cond}</div> <div class="label">종목</div><div class="value">{s_item}</div></div>
                                        </div>
                                    </div>
                                    {total_amount_html}
                                    <table class="main-table">
                                        <thead>
                                            <tr>
                                            <th width="{s["w_date"]}%">월일</th><th width="{s["w_item"]}%">품목</th><th width="{s["w_spec"]}%">규격</th><th width="{s["w_qty"]}%">수량</th>
                                            {price_header}
                                            <th width="{s["w_note"]}%">비고</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                            """
                            
                            for item in print_items_list:
                                price_cols = f"""<td class="right">{item['단가']:,}</td><td class="right">{item['공급가액']:,}</td><td class="right">{item['세액']:,}</td>""" if not s['opt_hide_price'] else "<td></td><td></td><td></td>"
                                page_html += f"""<tr><td class="center">{item['월일']}</td><td>{item['품목']}</td><td class="center">{item['규격']}</td><td class="right">{item['수량']:,}</td>{price_cols}<td>{item['비고']}</td></tr>"""
                            
                            # [수정] 빈 줄 채우기 (사용자 설정 행 수 적용)
                            for _ in range(max(0, s['rows'] - len(print_items_list))):
                                empty_price = "<td></td><td></td><td></td>"
                                page_html += f"<tr><td>&nbsp;</td><td></td><td></td><td></td>{empty_price}<td></td></tr>"
                            
                            # 합계 행
                            total_qty = sum([x['수량'] for x in print_items_list])
                            colspan_sum = 3
                            colspan_total = 5
                            
                            sum_row = ""
                            if not s['opt_hide_price']:
                                sum_row = f"""<tr class="total-row"><td colspan="{colspan_sum}" class="center">합 계</td><td class="right">{total_qty:,}</td><td></td><td class="right">{total_supply:,}</td><td class="right">{total_tax:,}</td><td></td></tr>
                                            <tr class="total-row"><td colspan="{colspan_sum}" class="center">총 합 계</td><td colspan="{colspan_total}" class="right" style="font-size: 14px;">₩ {grand_total:,}</td></tr>"""
                            else:
                                sum_row = f"""<tr class="total-row"><td colspan="{colspan_sum}" class="center">합 계</td><td class="right">{total_qty:,}</td><td></td><td></td><td></td><td></td></tr>"""

                            page_html += f"""</tbody><tfoot>{sum_row}</tfoot></table>
                                    <div style="margin-top: 5px; font-size: 12px;">{bank_info}</div>
                                    <div style="margin-top: 5px; font-size: 12px;">{s['opt_note']}</div>
                                    {sign_html}
                                </div>
                            """
                            return page_html

                        # 인쇄 옵션에 따라 페이지 생성
                        if s['opt_type'] == "공급받는자용":
                            html = html_template + create_page("공급받는자용", False)
                        elif s['opt_type'] == "공급자용":
                            html = html_template + create_page("공급자용", True)
                        elif s['opt_type'] == "표시 없음":
                            html = html_template + create_page("", False)
                        else: # 모두 인쇄
                            html = html_template + create_page("공급받는자용", False)
                            html += "<div class='page-break'></div>"
                            html += create_page("공급자용", True)

                        html += f"<!-- {uuid.uuid4()} -->" # [FIX] 매번 다른 내용을 추가하여 강제 리로드 유도
                        html += "</body></html>"

                        # [수정] 세션 상태와 미리보기를 제거하고, 버튼 클릭 시 보이지 않는 컴포넌트로 직접 인쇄창을 호출합니다.
                        # 이렇게 하면 재인쇄 시 발생하던 오류가 해결됩니다.
                        st.components.v1.html(html, height=0, width=0)