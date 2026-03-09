import streamlit as st
import pandas as pd
import datetime
import io
import uuid
import re
from firebase_admin import firestore
from utils import get_partners, generate_report_html, get_common_codes, search_address_api, get_products_list, save_user_settings, load_user_settings

def render_order_entry(db, sub_menu):
    st.header("발주서 접수")
    st.info("신규 발주서를 등록합니다. 개별 등록 또는 엑셀 일괄 업로드가 가능합니다.")
    
    # [NEW] 데이터프레임 리셋을 위한 동적 키 초기화
    if "order_df_key" not in st.session_state:
        st.session_state["order_df_key"] = 0

    if "del_orders_key" not in st.session_state:
        st.session_state["del_orders_key"] = 0

    # 발주 등록 성공 메시지 표시 (리런 후 유지)
    if "order_success_msg" in st.session_state:
        st.success(st.session_state["order_success_msg"])
        del st.session_state["order_success_msg"]
        
    # [수정] 발주 등록 후 초기화 로직
    if st.session_state.get("trigger_order_reset"):
        st.session_state["filter_pt"] = "전체"
        st.session_state["filter_yt"] = "전체"
        st.session_state["filter_wt"] = "전체"
        st.session_state["filter_sz"] = "전체"
        # 키 값을 변경하여 강제로 선택 해제 (새로운 데이터프레임으로 인식)
        st.session_state["order_df_key"] += 1
        del st.session_state["trigger_order_reset"]

    # 제품 목록 미리 가져오기 (공통 사용)
    # [최적화] 캐싱된 함수 사용
    products_data = get_products_list()
    if not products_data:
        st.warning("등록된 제품이 없습니다. [기초정보관리 > 제품 관리] 메뉴에서 먼저 제품을 등록해주세요.")
        st.stop()
    
    # 데이터프레임 변환 (개별 접수용)
    df_products = pd.DataFrame(products_data)
    
    # 구버전 데이터 호환
    if "weaving_type" in df_products.columns and "product_type" not in df_products.columns:
        df_products.rename(columns={"weaving_type": "product_type"}, inplace=True)

    # [수정] sub_menu가 없거나 '개별 접수'인 경우 기본 화면 표시
    if sub_menu == "개별 접수" or sub_menu is None:
        # --- 1. 제품 선택 ---
        st.subheader("1. 제품 선택")

        # 표시할 컬럼 설정
        col_map = {
            "product_code": "제품코드", "product_type": "제품종류", "yarn_type": "사종",
            "weight": "중량(g)", "size": "사이즈"
        }
        display_cols = ["product_code", "product_type", "yarn_type", "weight", "size"]
        final_cols = [c for c in display_cols if c in df_products.columns]

        # 검색 필터 추가
        with st.expander("검색", expanded=True):
            f1, f2, f3, f4 = st.columns(4)
            
            # [수정] 기초 코드 가져오기 및 정렬 (코드 순) - 재고임의등록과 동일한 방식
            pt_codes = get_common_codes("product_types", [])
            yt_codes = get_common_codes("yarn_types_coded", [])
            wt_codes = get_common_codes("weight_codes", [])
            sz_codes = get_common_codes("size_codes", [])
            
            # 코드 기준 정렬
            pt_codes.sort(key=lambda x: x.get('code', ''))
            yt_codes.sort(key=lambda x: x.get('code', ''))
            wt_codes.sort(key=lambda x: x.get('code', ''))
            sz_codes.sort(key=lambda x: x.get('code', ''))
            
            # 필터 옵션 생성 함수 (기초 코드 기반 + 실제 데이터 존재 여부 확인)
            def get_sorted_options(col_name, code_list, is_weight=False):
                if col_name not in df_products.columns:
                    return ["전체"]
                
                # 실제 데이터에 존재하는 값들
                existing_values = set(df_products[col_name].dropna().unique())
                
                options = ["전체"]
                
                # 1. 기초 코드에 정의된 순서대로 추가
                for item in code_list:
                    name = item.get('name', '')
                    code = item.get('code', '')
                    
                    # 중량의 경우 데이터는 숫자(int)일 수 있고 코드는 문자열일 수 있음
                    if is_weight:
                        try:
                            # 데이터에 해당 중량(숫자)이 있는지 확인
                            if int(code) in existing_values:
                                options.append(name)
                                continue
                        except:
                            pass
                    
                    # 일반적인 경우 (이름으로 매칭)
                    if name in existing_values:
                        options.append(name)
                
                # 2. 기초 코드에는 없지만 데이터에는 있는 값들 추가 (기타 값)
                if is_weight:
                    # 기초 코드에 매핑되지 않은 값 찾기
                    mapped_values = set()
                    for item in code_list:
                        try: mapped_values.add(int(item.get('code')))
                        except: pass
                    
                    for val in existing_values:
                        if val not in mapped_values:
                            options.append(str(val))
                else:
                    # 일반 컬럼
                    mapped_names = set([item.get('name') for item in code_list])
                    for val in existing_values:
                        if val not in mapped_names:
                            options.append(str(val))
                            
                return options

            # 각 필드별 옵션 생성
            opt_pt = get_sorted_options("product_type", pt_codes)
            opt_yt = get_sorted_options("yarn_type", yt_codes)
            opt_wt = get_sorted_options("weight", wt_codes, is_weight=True)
            opt_sz = get_sorted_options("size", sz_codes)
            
            s_type = f1.selectbox("제품종류", opt_pt, key="filter_pt")
            s_yarn = f2.selectbox("사종", opt_yt, key="filter_yt")
            s_weight = f3.selectbox("중량", opt_wt, key="filter_wt")
            s_size = f4.selectbox("사이즈", opt_sz, key="filter_sz")

        # 필터링 적용
        df_filtered = df_products.copy()
        if s_type != "전체":
            df_filtered = df_filtered[df_filtered['product_type'].astype(str) == s_type]
        if s_yarn != "전체":
            df_filtered = df_filtered[df_filtered['yarn_type'].astype(str) == s_yarn]
        if s_weight != "전체":
            # 중량 필터링: 선택된 명칭(s_weight)에 해당하는 코드값 찾기
            target_code = None
            # 1. 기초 코드에서 찾기
            for item in wt_codes:
                if item.get('name') == s_weight:
                    target_code = item.get('code')
                    break
            
            if target_code:
                try:
                    # 숫자로 변환하여 비교
                    target_val = int(target_code)
                    df_filtered = df_filtered[df_filtered['weight'] == target_val]
                except:
                    df_filtered = df_filtered[df_filtered['weight'].astype(str) == str(target_code)]
            else:
                # 기초 코드에 없는 값인 경우 문자열로 비교
                df_filtered = df_filtered[df_filtered['weight'].astype(str) == s_weight]

        if s_size != "전체":
            df_filtered = df_filtered[df_filtered['size'].astype(str) == s_size]

        # [NEW] 콤보박스 제품 선택 (재고 임의등록과 동일한 방식)
        st.write("🔽 발주할 제품을 선택하세요.")
        
        # 옵션 생성: 코드 : 종류 / 사종 / 중량 / 사이즈
        product_opts = ["선택하세요"] + [f"{row['product_code']} : {row.get('product_type', '')} / {row.get('yarn_type', '')} / {row.get('weight', '')}g / {row.get('size', '')}" for _, row in df_filtered.iterrows()]
        
        # [NEW] 선택박스 초기화 (세션 상태가 없으면 기본값 설정)
        if "order_prod_selectbox" not in st.session_state:
            st.session_state["order_prod_selectbox"] = "선택하세요"

        # [FIX] 동기화 로직을 위젯 렌더링 이전으로 이동 (StreamlitAPIException 방지)
        last_code = st.session_state.get("last_sel_product_code")
        
        # 1. Dataframe 선택 상태 확인
        df_key = f"order_product_select_{st.session_state['order_df_key']}"
        df_state = st.session_state.get(df_key)
        df_selected_code = None
        if df_state and df_state.get("selection") and df_state["selection"].get("rows"):
            idx = df_state["selection"]["rows"][0]
            if idx < len(df_filtered):
                df_selected_code = df_filtered.iloc[idx]['product_code']
        
        # 2. Selectbox 선택 상태 확인
        sb_val = st.session_state.get("order_prod_selectbox")
        sb_selected_code = None
        if sb_val and sb_val != "선택하세요":
            sb_selected_code = sb_val.split(" : ")[0]
            
        # 3. 변경 감지 및 동기화 (우선순위 결정)
        current_code = last_code
        
        # Case A: 목록에서 다른 행을 선택함
        if df_selected_code and df_selected_code != last_code:
            current_code = df_selected_code
            # 콤보박스 업데이트
            match_opt = next((opt for opt in product_opts if opt.startswith(f"{current_code} :")), "선택하세요")
            st.session_state["order_prod_selectbox"] = match_opt
            
        # Case B: 콤보박스에서 다른 제품을 선택함
        elif sb_selected_code and sb_selected_code != last_code:
            current_code = sb_selected_code
            # 목록 선택 해제 (키 변경)
            if df_selected_code != current_code:
                 st.session_state["order_df_key"] += 1
        
        # Case C: 목록 선택 해제 (사용자가 선택된 행을 다시 클릭)
        elif last_code and not df_selected_code and sb_selected_code == last_code:
             current_code = None
             st.session_state["order_prod_selectbox"] = "선택하세요"

        # 상태 업데이트
        if current_code != last_code:
            st.session_state["last_sel_product_code"] = current_code
            # [FIX] 제품 변경 시 주소 검색 팝업 닫기
            st.session_state["show_order_addr_dialog"] = False

        # --- 위젯 렌더링 ---
        sel_prod_str = st.selectbox("제품 선택 (검색 가능)", product_opts, key="order_prod_selectbox")

        with st.expander("제품 목록", expanded=True):
            st.caption("목록에서 행을 클릭하여 선택할 수도 있습니다.")
            selection = st.dataframe(
                df_filtered[final_cols].rename(columns=col_map),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"order_product_select_{st.session_state['order_df_key']}"
            )

        # 선택된 제품 정보 가져오기
        selected_product = None
        if current_code:
            found = df_filtered[df_filtered['product_code'] == current_code]
            if not found.empty:
                selected_product = found.iloc[0].to_dict()

        if not selected_product:
            st.info("👆 위 목록에서 제품을 선택하면 발주 입력 폼이 나타납니다.")
            # 선택이 없으면 상태 초기화
            if st.session_state.get("last_sel_product_code") is not None:
                st.session_state["last_sel_product_code"] = None
        else:
            # [NEW] 자동 스크롤 앵커 및 스크립트
            st.markdown('<div id="order-entry-form"></div>', unsafe_allow_html=True)
            js_uuid = uuid.uuid4()
            st.components.v1.html(
                f"""
                <script>
                    setTimeout(function() {{
                        // Force re-run: {js_uuid}
                        function attemptScroll(count) {{
                            const anchor = window.parent.document.getElementById('order-entry-form');
                            if (anchor) {{
                                anchor.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                            }} else if (count > 0) {{
                                setTimeout(() => attemptScroll(count - 1), 100);
                            }}
                        }}
                        attemptScroll(10);
                    }}, 200);
                </script>
                """, height=0
            )

            st.divider()
            c_info, c_close = st.columns([5.5, 1.5])
            with c_info:
                st.success(f"선택된 제품: **{selected_product['product_code']}**\n\n제품종류: {selected_product.get('product_type', '')} | 사종: {selected_product.get('yarn_type', '')} | 중량: {selected_product.get('weight', '')}g | 사이즈: {selected_product.get('size', '')}")
            
            # [FIX] 버튼 클릭 시 콜백 함수로 상태 초기화 (StreamlitAPIException 방지)
            def reset_order_selection():
                st.session_state["order_df_key"] += 1
                st.session_state["last_sel_product_code"] = None
                st.session_state["order_prod_selectbox"] = "선택하세요"
                st.session_state["show_order_addr_dialog"] = False

            with c_close:
                st.button("닫기", key="close_order_detail", use_container_width=True, on_click=reset_order_selection)

            # [NEW] 주소 검색 모달 (Dialog)
            if "show_order_addr_dialog" not in st.session_state:
                st.session_state.show_order_addr_dialog = False

            @st.dialog("주소 검색")
            def show_address_search_modal_order():
                # 페이지네이션 및 검색어 상태 관리
                if "o_addr_keyword" not in st.session_state:
                    st.session_state.o_addr_keyword = ""
                if "o_addr_page" not in st.session_state:
                    st.session_state.o_addr_page = 1

                # 검색 폼 (Enter로 검색 가능)
                with st.form("addr_search_form_order"):
                    keyword_input = st.text_input("도로명 또는 지번 주소 입력", value=st.session_state.o_addr_keyword, placeholder="예: 세종대로 209")
                    if st.form_submit_button("검색"):
                        st.session_state.o_addr_keyword = keyword_input
                        st.session_state.o_addr_page = 1 # 새 검색 시 1페이지로
                        st.rerun()

                # 검색 실행 및 결과 표시
                if st.session_state.o_addr_keyword:
                    results, common, error = search_address_api(st.session_state.o_addr_keyword, st.session_state.o_addr_page)
                    if error:
                        st.error(error)
                    elif results:
                        st.session_state['o_addr_results'] = results
                        st.session_state['o_addr_common'] = common
                    else:
                        st.warning("검색 결과가 없습니다.")
                
                if 'o_addr_results' in st.session_state:
                    for idx, item in enumerate(st.session_state['o_addr_results']):
                        road = item['roadAddr']
                        zip_no = item['zipNo']
                        full_addr = f"({zip_no}) {road}"
                        if st.button(f"{full_addr}", key=f"sel_o_{zip_no}_{road}_{idx}"):
                            st.session_state["order_del_addr"] = full_addr
                            # 검색 관련 세션 상태 정리
                            st.session_state.show_order_addr_dialog = False # 팝업 닫기
                            for k in ['o_addr_keyword', 'o_addr_page', 'o_addr_results', 'o_addr_common']:
                                if k in st.session_state:
                                    del st.session_state[k]
                            st.rerun()

                    # 페이지네이션 UI
                    common_info = st.session_state.get('o_addr_common', {})
                    if common_info:
                        total_count = int(common_info.get('totalCount', 0))
                        current_page = int(common_info.get('currentPage', 1))
                        count_per_page = int(common_info.get('countPerPage', 10))
                        total_pages = (total_count + count_per_page - 1) // count_per_page if total_count > 0 else 1
                        
                        if total_pages > 1:
                            st.divider()
                            p_cols = st.columns([1, 2, 1])
                            if p_cols[0].button("◀ 이전", disabled=(current_page <= 1)):
                                st.session_state.o_addr_page -= 1
                                st.rerun()
                            p_cols[1].write(f"페이지 {current_page} / {total_pages}")
                            if p_cols[2].button("다음 ▶", disabled=(current_page >= total_pages)):
                                st.session_state.o_addr_page += 1
                                st.rerun()
                
                st.divider()
                if st.button("닫기", key="close_addr_order", use_container_width=True):
                    st.session_state.show_order_addr_dialog = False
                    st.rerun()

            # --- 2. 발주 정보 입력 ---
            # [수정] st.form 제거 (주소 검색 팝업 유지 및 레이아웃 개선을 위해)
            st.subheader("2. 발주 상세 정보 입력")
            
            customer_list = get_partners("발주처")

            c1, c2, c3, c4 = st.columns(4)
            order_date = c1.date_input("발주접수일", datetime.date.today(), format="YYYY-MM-DD")
            order_type = c2.selectbox("신규/추가 구분", ["신규제직", "추가제직"])
            if customer_list:
                customer = c3.selectbox("발주처 선택", customer_list)
            else:
                customer = c3.text_input("발주처 (기초정보관리에서 거래처를 등록하세요)")
            delivery_req_date = c4.date_input("납품요청일", datetime.date.today() + datetime.timedelta(days=7), format="YYYY-MM-DD")

            c1, c2, c3 = st.columns(3)
            name = c1.text_input("제품명 (고객사 요청 제품명)", help="고객사가 부르는 제품명을 입력하세요. 예: 프리미엄 호텔타올")
            color = c2.text_input("색상")
            stock = c3.number_input("수량(장)", min_value=0, step=10)

            st.subheader("납품 및 기타 정보")
            
            c1, c2 = st.columns(2)
            delivery_to = c1.text_input("납품처")
            delivery_contact = c2.text_input("납품 연락처")
            
            # [수정] 주소 입력 필드 레이아웃 변경 (주소 - 상세주소 - 버튼)
            c_addr1, c_addr2, c_addr3 = st.columns([3.5, 2, 0.5], vertical_alignment="bottom")
            delivery_address = c_addr1.text_input("납품 주소", key="order_del_addr")
            delivery_addr_detail = c_addr2.text_input("상세주소", key="order_del_addr_detail")
            if c_addr3.button("🔍 주소", key="btn_search_addr_order", use_container_width=True):
                # [NEW] 팝업 열 때 검색 상태 초기화
                for k in ['o_addr_keyword', 'o_addr_page', 'o_addr_results', 'o_addr_common']:
                    if k in st.session_state: del st.session_state[k]
                st.session_state.show_order_addr_dialog = True
                st.rerun()
            
            if st.session_state.show_order_addr_dialog:
                show_address_search_modal_order()
            
            note = st.text_area("특이사항")
            
            if st.button("발주 등록", type="primary"):
                if name and customer:
                    # 발주번호 생성 로직 (YYMM + 3자리 일련번호, 예: 2505001)
                    now = datetime.datetime.now()
                    prefix = now.strftime("%y%m") # 예: 2405
                    
                    # [수정] 발주번호 생성 및 중복 방지 재시도 로직
                    order_no = ""
                    max_retries = 3
                    
                    for attempt in range(max_retries):
                        # 해당 월의 가장 마지막 발주번호 조회
                        last_docs = db.collection("orders")\
                            .where("order_no", ">=", f"{prefix}000")\
                            .where("order_no", "<=", f"{prefix}999")\
                            .order_by("order_no", direction=firestore.Query.DESCENDING)\
                            .limit(1)\
                            .stream()
                        
                        last_seq = 0
                        for doc in last_docs:
                            last_val = doc.to_dict().get("order_no")
                            if last_val and len(last_val) == 7:
                                try:
                                    last_seq = int(last_val[-3:])
                                except:
                                    pass
                        
                        # 시도 횟수에 따라 번호 증가 (동시 충돌 시 회피)
                        new_seq = last_seq + 1 + attempt
                        temp_order_no = f"{prefix}{new_seq:03d}"
                        
                        # [안전장치] DB에 해당 번호가 진짜 없는지 이중 확인
                        dup_check = list(db.collection("orders").where("order_no", "==", temp_order_no).limit(1).stream())
                        if not dup_check:
                            order_no = temp_order_no
                            break
                    
                    if not order_no:
                        st.error("발주번호 생성 중 충돌이 발생했습니다. 잠시 후 다시 시도해주세요.")
                        st.stop()

                    # 주소 합치기
                    full_delivery_addr = f"{delivery_address} {delivery_addr_detail}".strip()

                    # Firestore에 저장할 데이터 딕셔너리 생성
                    doc_data = {
                        # 제품 마스터 정보 (Denormalized)
                        "product_code": selected_product['product_code'],
                        "product_type": selected_product.get('product_type', selected_product.get('weaving_type')), # 필드명 변경
                        "yarn_type": selected_product.get('yarn_type'),
                        "weight": selected_product['weight'],
                        "size": selected_product['size'],
                        
                        # 주문 고유 정보
                        "order_no": order_no,
                        "date": datetime.datetime.combine(order_date, datetime.time.min),
                        "order_type": order_type,
                        "customer": customer,
                        "delivery_req_date": str(delivery_req_date),
                        "name": name, # 고객사 제품명
                        "color": color,
                        "stock": stock,
                        "delivery_to": delivery_to,
                        "delivery_contact": delivery_contact,
                        "delivery_address": full_delivery_addr,
                        "note": note,
                        "status": "발주접수" # 초기 상태
                    }
                    db.collection("orders").add(doc_data) # 'orders' 컬렉션에 저장
                    st.success(f"발주번호 [{order_no}] 접수 완료!")
                    st.session_state["order_success_msg"] = f"✅ 발주번호 [{order_no}]가 성공적으로 등록되었습니다."
                    
                    # [NEW] 입력 필드 수동 초기화 (clear_on_submit 제거로 인해 필요)
                    keys_to_clear = ["order_del_addr", "order_del_addr_detail"]
                    for k in keys_to_clear: st.session_state[k] = ""
                    
                    st.session_state["trigger_order_reset"] = True
                    st.rerun()
                else:
                    st.error("제품명과 발주처는 필수 입력 항목입니다.")

def render_partner_order_status(db):
    st.header("발주 현황 조회 (거래처용)")
    
    # [NEW] 목록 갱신을 위한 키 초기화
    if "partner_order_key" not in st.session_state:
        st.session_state["partner_order_key"] = 0
    
    partner_name = st.session_state.get("linked_partner")
    if not partner_name:
        st.error("연동된 거래처 정보가 없습니다. 관리자에게 문의하세요.")
        return

    st.info(f"**{partner_name}**님의 발주 내역 및 현재 공정 상태를 조회합니다.")

    # 검색 조건
    with st.expander("검색", expanded=True):
        with st.form("partner_search_form"):
            c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 2])
            today = datetime.date.today()
            date_range = c1.date_input("조회 기간 (접수일)", [today - datetime.timedelta(days=90), today])
            
            # 상태 필터
            status_options = ["전체", "미출고(출고완료 제외)", "발주접수", "제직대기", "제직중", "제직완료", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
            filter_status = c2.selectbox("진행 상태", status_options)
            
            # [NEW] 검색 기준 및 키워드 (거래처용)
            criteria_options = ["전체", "제품명", "제품코드", "제품종류", "사종", "색상"]
            search_criteria = c3.selectbox("검색 기준", criteria_options)
            search_keyword = c4.text_input("검색어 입력")
            
            c_b1, c_b2 = st.columns([1, 6])
            with c_b1:
                st.form_submit_button("조회", use_container_width=True)

    # 데이터 조회
    start_date = datetime.datetime.combine(date_range[0], datetime.time.min)
    end_date = datetime.datetime.combine(date_range[1], datetime.time.max) if len(date_range) > 1 else datetime.datetime.combine(date_range[0], datetime.time.max)

    # [수정] 복합 인덱스 오류 방지를 위해 customer로만 1차 조회 후 메모리 필터링
    docs = db.collection("orders").where("customer", "==", partner_name).stream()
    
    rows = []
    for doc in docs:
        d = doc.to_dict()
        
        # 1. 날짜 필터링 (메모리)
        d_date = d.get('date')
        if d_date:
            if d_date.tzinfo: d_date = d_date.replace(tzinfo=None)
            if not (start_date <= d_date <= end_date):
                continue
        else:
            continue
            
        # 2. 상태 필터링 (메모리)
        if filter_status == "미출고(출고완료 제외)":
            if d.get('status') == '출고완료':
                continue
        elif filter_status != "전체" and d.get('status') != filter_status:
            continue
            
        # [NEW] 3. 검색어 필터 (메모리)
        if search_keyword:
            search_keyword = search_keyword.lower()
            if search_criteria == "전체":
                # 주요 필드 통합 검색
                target_str = f"{d.get('name','')} {d.get('product_code','')} {d.get('product_type','')} {d.get('yarn_type','')} {d.get('color','')} {d.get('note','')}"
                if search_keyword not in target_str.lower(): continue
            else:
                # 특정 필드 검색
                field_map = {"제품명": "name", "제품코드": "product_code", "제품종류": "product_type", "사종": "yarn_type", "색상": "color"}
                target_field = field_map.get(search_criteria)
                if target_field and search_keyword not in str(d.get(target_field, '')).lower():
                    continue
            
        # 정렬을 위해 원본 날짜 임시 저장
        d['_sort_date'] = d.get('date')

        # 마스터 완료 상태 표시 변경
        if d.get('status') == "제직완료(Master)":
            d['status'] = "제직완료"
            
        if 'date' in d and d['date']:
            d['date'] = d['date'].strftime("%Y-%m-%d")
        if 'delivery_req_date' in d:
             val = d['delivery_req_date']
             # [수정] None이나 nan 문자열이 들어가지 않도록 처리
             d['delivery_req_date'] = str(val)[:10] if val and str(val).lower() not in ['nan', 'none', 'nat'] else ""
             
        rows.append(d)
        
    # 3. 날짜 기준 내림차순 정렬
    rows.sort(key=lambda x: x.get('_sort_date', datetime.datetime.min), reverse=True)

    if rows:
        df = pd.DataFrame(rows)
        
        # [수정] 컬럼 매핑 확장 및 발주처 제외
        col_map = {
            "order_no": "발주번호", "status": "현재상태", "date": "접수일", 
            "name": "제품명", "product_type": "제품종류", "yarn_type": "사종",
            "color": "색상", "weight": "중량", "size": "사이즈", "stock": "발주수량", 
            "delivery_req_date": "납품요청일", "delivery_to": "납품처",
            "delivery_contact": "연락처", "delivery_address": "주소", "note": "비고"
        }
        # customer 제외, 상세 정보 포함
        display_cols = ["date", "order_no", "status", "name", "product_type", "yarn_type", "color", "weight", "size", "stock", "delivery_req_date", "delivery_to", "delivery_contact", "delivery_address", "note"]
        final_cols = [c for c in display_cols if c in df.columns]
        
        df_display = df[final_cols].rename(columns=col_map)
        # [수정] NaN/NaT 및 문자열 "nan", "None" 등을 빈 문자열로 변환
        df_display = df_display.fillna("")
        df_display = df_display.replace(["nan", "None", "NaT"], "")
        
        # [NEW] 동적 높이 계산 (행당 약 35px, 최대 20행 700px)
        table_height = min((len(df_display) + 1) * 35 + 3, 700)

        st.write("🔽 상세 이력을 확인할 항목을 선택하세요.")
        selection = st.dataframe(
            df_display, 
            width="stretch", 
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            height=table_height,
            key=f"partner_order_list_{st.session_state['partner_order_key']}"
        )

        if df_display.empty:
            st.markdown("<br>", unsafe_allow_html=True)
        
        # [NEW] 선택 시 상세 이력 표시
        if selection.selection.rows:
            idx = selection.selection.rows[0]
            sel_row = df.iloc[idx]
            
            st.divider()
            c_sub, c_close = st.columns([7.5, 1.5])
            with c_sub:
                st.subheader(f"상세 이력 정보: {sel_row['name']} ({sel_row['order_no']})")
            with c_close:
                if st.button("닫기", key="close_detail_view_partner", use_container_width=True):
                    st.session_state["partner_order_key"] += 1
                    st.rerun()

            # 포맷팅 함수들
            def fmt_dt(val):
                if pd.isna(val) or val == "" or val is None: return "-"
                if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d %H:%M")
                if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d %H:%M")
                return str(val)[:16]
            
            def fmt_date(val):
                if pd.isna(val) or val == "" or val is None: return "-"
                if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d")
                if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d")
                return str(val)[:10]

            # [NEW] 공정별 개별 테이블 표시 (민감 정보 제외)
            
            # --- 1. 제직 공정 ---
            st.markdown("##### 제직 공정")
            weaving_data = []
            if sel_row.get('weaving_start_time'):
                w_status = "진행중"
                if sel_row.get('weaving_end_time'):
                    w_status = "완료"
                
                weaving_data.append({
                    "상태": w_status,
                    "시작일시": fmt_dt(sel_row.get('weaving_start_time')),
                    "완료일시": fmt_dt(sel_row.get('weaving_end_time')),
                })
            
            if weaving_data:
                st.dataframe(pd.DataFrame(weaving_data), hide_index=True, use_container_width=True)
            else:
                st.info("제직 공정 대기 중입니다.")

            # --- 2. 염색 공정 ---
            st.markdown("##### 염색 공정")
            dyeing_data = []
            if sel_row.get('dyeing_out_date'):
                d_status = "진행중"
                if sel_row.get('dyeing_in_date'):
                    d_status = "완료"
                
                dyeing_data.append({
                    "상태": d_status,
                    "시작일": fmt_date(sel_row.get('dyeing_out_date')),
                    "완료일": fmt_date(sel_row.get('dyeing_in_date')),
                })

            if dyeing_data:
                st.dataframe(pd.DataFrame(dyeing_data), hide_index=True, use_container_width=True)
            else:
                st.info("염색 공정 대기 중입니다.")

            # --- 3. 봉제 공정 ---
            st.markdown("##### 봉제 공정")
            sewing_data = []
            if sel_row.get('sewing_start_date'):
                s_status = "진행중"
                if sel_row.get('sewing_end_date'):
                    s_status = "완료"
                
                sewing_data.append({
                    "상태": s_status,
                    "시작일": fmt_date(sel_row.get('sewing_start_date')),
                    "완료일": fmt_date(sel_row.get('sewing_end_date')),
                })
            
            if sewing_data:
                st.dataframe(pd.DataFrame(sewing_data), hide_index=True, use_container_width=True)
            else:
                st.info("봉제 공정 대기 중입니다.")

        st.divider()
        
        # [NEW] 인쇄 옵션 설정
        with st.expander("인쇄 옵션 설정"):
            po_c1, po_c2, po_c3, po_c4 = st.columns(4)
            p_title = po_c1.text_input("제목", value=f"발주 현황 ({partner_name})", key="po_title")
            p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key="po_ts")
            p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key="po_bs")
            p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key="po_pad")
            
            po_c5, po_c6, po_c7 = st.columns(3)
            p_show_date = po_c5.checkbox("출력일시 표시", value=True, key="po_sd")
            p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key="po_dp")
            p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key="po_ds")
            
            st.caption("페이지 여백 (mm)")
            po_c8, po_c9, po_c10, po_c11 = st.columns(4)
            p_m_top = po_c8.number_input("상단", value=15, step=1, key="po_mt")
            p_m_bottom = po_c9.number_input("하단", value=15, step=1, key="po_mb")
            p_m_left = po_c10.number_input("좌측", value=15, step=1, key="po_ml")
            p_m_right = po_c11.number_input("우측", value=15, step=1, key="po_mr")
            
            po_c12, po_c13 = st.columns(2)
            po_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="po_bo")
            po_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="po_bi")

        # 엑셀 및 인쇄 버튼
        c1, c2 = st.columns([1, 1])
        
        # 엑셀 다운로드
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_display.to_excel(writer, index=False)
        c1.download_button(
            label="💾 엑셀 다운로드",
            data=buffer.getvalue(),
            file_name=f"발주현황_{partner_name}_{today}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # 인쇄 (옵션 적용)
        if c2.button("🖨️ 인쇄하기"):
            options = {
                'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none",
                'bo': po_bo, 'bi': po_bi
            }
            print_html = generate_report_html(p_title, df_display, "", options)
            st.components.v1.html(print_html, height=0, width=0)
    else:
        st.info("조회된 발주 내역이 없습니다.")

def render_order_status(db, sub_menu):
    st.header("발주 현황")
    user_id = st.session_state.get("user_id")

    # [NEW] 인쇄 설정 세션 상태 초기화 (최초 1회)
    print_options_keys = {
        "os_p_title": "발주 현황 리스트", "os_p_ts": 24, "os_p_bs": 11, "os_p_pad": 6,
        "os_p_sd": True, "os_p_dp": "Right", "os_p_ds": 12,
        "os_p_mt": 15, "os_p_mb": 15, "os_p_ml": 15, "os_p_mr": 15,
        "os_p_nowrap": False
    }
    
    # [NEW] DB에서 인쇄 설정 로드
    saved_print_opts = load_user_settings(user_id, "order_print_opts", {})
    
    for key, default_value in print_options_keys.items():
        if key not in st.session_state:
            st.session_state[key] = saved_print_opts.get(key, default_value)



    # [FIX] KeyError 방지를 위해 세션 키가 없으면 초기화
    if "del_orders_key" not in st.session_state:
        st.session_state["del_orders_key"] = 0

    # [NEW] 발주내역삭제(엑셀업로드) - 관리자 전용
    if sub_menu == "발주내역삭제(엑셀업로드)" and st.session_state.get("role") == "admin":
            st.subheader("엑셀 파일로 일괄 등록 (과거 데이터 포함)")
            st.markdown("""
            **업로드 규칙**
            1. 아래 **양식 다운로드** 버튼을 눌러 엑셀 파일을 받으세요.
            2. `제품코드`는 시스템에 등록된 코드와 정확히 일치해야 합니다.
            3. `현재상태`를 입력하면 해당 상태로 등록됩니다. (비워두면 '발주접수')
               - 예: 발주접수, 제직완료, 염색완료, 봉제완료, 출고완료 등
            4. 날짜 컬럼은 `YYYY-MM-DD` 형식으로 입력하세요.
            """)
            
            # 양식 다운로드
            template_data = {
                "접수일자": [datetime.date.today().strftime("%Y-%m-%d")],
                "구분": ["신규제직"],
                "발주처": ["예시상사"],
                "제품코드": ["A20S0904080"],
                "제품명(고객용)": ["호텔타올"],
                "색상": ["화이트"],
                "수량": [100],
                "납품요청일": [(datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")],
                "납품처": ["서울시 강남구..."],
                "납품연락처": ["010-0000-0000"],
                "납품주소": ["서울시..."],
                "비고": ["기초데이터"],
                # [NEW] 상태 및 상세 정보 컬럼 추가
                "현재상태": ["출고완료"],
                "제직기번호": [1],
                "제직완료일": ["2024-01-01"],
                "생산수량": [100],
                "생산중량": [20.5],
                "염색업체": ["태광염색"],
                "염색입고일": ["2024-01-05"],
                "봉제업체": ["미소봉제"],
                "봉제완료일": ["2024-01-10"],
                "출고일": ["2024-01-15"],
                "배송방법": ["택배"],
                "배송업체": ["경동택배"],
                "운임비": [5000]
            }
            df_template = pd.DataFrame(template_data)
            
            # 제품 목록 미리 가져오기 (매핑용)
            product_docs = list(db.collection("products").order_by("product_code").stream())
            products_data = [doc.to_dict() for doc in product_docs]
            # 구버전 데이터 호환
            for p in products_data:
                if "weaving_type" in p and "product_type" not in p: p["product_type"] = p["weaving_type"]
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_template.to_excel(writer, index=False)
                
            st.download_button(
                label="📥 업로드용 양식 다운로드",
                data=buffer.getvalue(),
                file_name="발주업로드양식.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx", "xls"])
            
            if uploaded_file:
                try:
                    df_upload = pd.read_excel(uploaded_file)
                    st.write("데이터 미리보기:")
                    st.dataframe(df_upload.head())
                    
                    # [NEW] 중복 방지를 위한 초기화 옵션 및 삭제 제외 설정 (UI 변경)
                    st.markdown("---")
                    c_del_main, c_del_sub = st.columns([1.2, 3])
                    
                    with c_del_main:
                        delete_existing = st.checkbox("⚠️ 기존 데이터 삭제 후 업로드", value=False, help="체크하면 현재 시스템에 등록된 모든 발주 내역을 삭제하고, 엑셀 파일의 내용으로 새로 등록합니다.")
                    
                    preserve_list = []
                    with c_del_sub:
                        st.caption("🛡️ 삭제 제외 상태 (체크한 상태의 데이터는 유지됩니다)")
                        # 체크박스 나열
                        pc1, pc2, pc3, pc4 = st.columns(4)
                        is_disabled = not delete_existing
                        
                        if pc1.checkbox("제직완료", value=False, disabled=is_disabled): preserve_list.append("제직완료")
                        if pc2.checkbox("염색완료", value=False, disabled=is_disabled): preserve_list.append("염색완료")
                        if pc3.checkbox("봉제완료", value=False, disabled=is_disabled): preserve_list.append("봉제완료")
                        if pc4.checkbox("출고완료", value=True, disabled=is_disabled): preserve_list.append("출고완료")

                    if st.button("일괄 등록 시작", type="primary"):
                        # [NEW] 기존 데이터 삭제 로직
                        if delete_existing:
                            with st.spinner("기존 데이터를 삭제하고 있습니다..."):
                                all_docs = db.collection("orders").stream()
                                del_count = 0
                                batch = db.batch()
                                for doc in all_docs:
                                    # [NEW] 선택된 상태 유지 옵션
                                    doc_status = doc.to_dict().get('status')
                                    
                                    # 제직완료 선택 시 Master도 포함하여 유지
                                    if "제직완료" in preserve_list and doc_status == "제직완료(Master)":
                                        continue
                                        
                                    if doc_status in preserve_list:
                                        continue
                                        
                                    batch.delete(doc.reference)
                                    del_count += 1
                                    if del_count % 400 == 0:
                                        batch.commit()
                                        batch = db.batch()
                                batch.commit()
                            
                            excluded_msg = f"(제외된 상태: {', '.join(preserve_list)})" if preserve_list else ""
                            st.warning(f"기존 데이터 {del_count}건을 삭제했습니다. {excluded_msg} 신규 등록을 시작합니다.")

                        # 제품 코드 매핑을 위한 딕셔너리 생성
                        product_map = {p['product_code']: p for p in products_data}
                        
                        # 발주번호 생성을 위한 마지막 번호 조회
                        now = datetime.datetime.now()
                        prefix = now.strftime("%y%m")
                        last_docs = db.collection("orders").where("order_no", ">=", f"{prefix}000").where("order_no", "<=", f"{prefix}999").order_by("order_no", direction=firestore.Query.DESCENDING).limit(1).stream()
                        last_seq = 0
                        for doc in last_docs:
                            last_val = doc.to_dict().get("order_no")
                            if last_val and len(last_val) == 7:
                                try: last_seq = int(last_val[-3:])
                                except: pass
                        
                        success_count = 0
                        error_logs = []
                        
                        progress_bar = st.progress(0)
                        
                        for idx, row in df_upload.iterrows():
                            p_code = str(row.get("제품코드", "")).strip()
                            if p_code not in product_map:
                                error_logs.append(f"{idx+2}행: 제품코드 '{p_code}'가 존재하지 않습니다.")
                                continue
                                
                            product_info = product_map[p_code]
                            last_seq += 1
                            order_no = f"{prefix}{last_seq:03d}"
                            
                            # 날짜 파싱 헬퍼 함수
                            def parse_date_val(val):
                                if pd.isna(val) or str(val).strip() == "": return None
                                try: return pd.to_datetime(val).to_pydatetime()
                                except: return None
                            
                            def parse_str_date(val):
                                if pd.isna(val) or str(val).strip() == "": return ""
                                return str(val)[:10]

                            reg_date = parse_date_val(row.get("접수일자")) or datetime.datetime.now()
                            
                            # 상태 처리
                            status = str(row.get("현재상태", "발주접수")).strip()
                            if not status or status == "nan": status = "발주접수"
                                
                            doc_data = {
                                "product_code": p_code,
                                "product_type": product_info.get('product_type', product_info.get('weaving_type')),
                                "yarn_type": product_info.get('yarn_type'),
                                "weight": product_info.get('weight'),
                                "size": product_info.get('size'),
                                
                                "order_no": order_no,
                                "date": reg_date,
                                "order_type": str(row.get("구분", "")),
                                "customer": str(row.get("발주처", "")),
                                "delivery_req_date": str(row.get("납품요청일", "")),
                                "name": str(row.get("제품명(고객용)", "")),
                                "color": str(row.get("색상", "")),
                                "stock": int(row.get("수량", 0)),
                                "delivery_to": str(row.get("납품처", "")),
                                "delivery_contact": str(row.get("납품연락처", "")),
                                "delivery_address": str(row.get("납품주소", "")),
                                "note": str(row.get("비고", "")),
                                "status": status,
                                
                                # [NEW] 상세 정보 매핑 (과거 데이터)
                                "machine_no": int(row.get("제직기번호", 0)) if pd.notna(row.get("제직기번호")) else None,
                                "weaving_end_time": parse_date_val(row.get("제직완료일")),
                                "real_stock": int(row.get("생산수량", 0)) if pd.notna(row.get("생산수량")) else 0,
                                "prod_weight_kg": float(row.get("생산중량", 0)) if pd.notna(row.get("생산중량")) else 0.0,
                                
                                "dyeing_partner": str(row.get("염색업체", "")),
                                "dyeing_in_date": parse_str_date(row.get("염색입고일")),
                                
                                "sewing_partner": str(row.get("봉제업체", "")),
                                "sewing_end_date": parse_str_date(row.get("봉제완료일")),
                                
                                "shipping_date": parse_date_val(row.get("출고일")),
                                "shipping_method": str(row.get("배송방법", "")),
                                "shipping_carrier": str(row.get("배송업체", "")),
                                "shipping_cost": int(row.get("운임비", 0)) if pd.notna(row.get("운임비")) else 0
                            }
                            
                            # nan 문자열 정리
                            for k, v in doc_data.items():
                                if isinstance(v, str) and v == "nan": doc_data[k] = ""
                            
                            db.collection("orders").add(doc_data)
                            success_count += 1
                            progress_bar.progress((idx + 1) / len(df_upload))
                            
                        if success_count > 0:
                            st.success(f"✅ {success_count}건의 발주가 성공적으로 등록되었습니다.")
                        
                        if error_logs:
                            st.error(f"⚠️ {len(error_logs)}건의 오류가 발생했습니다.")
                            for log in error_logs:
                                st.write(log)
                                
                except Exception as e:
                    st.error(f"파일 처리 중 오류가 발생했습니다: {e}")

            st.divider()
            st.subheader("발주 내역 삭제 (다중 선택)")
            st.info("삭제할 항목을 선택(체크)한 후 하단의 삭제 버튼을 누르세요. (헤더의 체크박스로 전체 선택 가능)")

            # 삭제 대상 목록 가져오기
            del_docs = list(db.collection("orders").order_by("date", direction=firestore.Query.DESCENDING).stream())
            
            if del_docs:
                del_rows = []
                for doc in del_docs:
                    d = doc.to_dict()
                    d['id'] = doc.id
                    del_rows.append(d)
                
                df_del = pd.DataFrame(del_rows)

                # 날짜 포맷
                if 'date' in df_del.columns:
                    df_del['date'] = df_del['date'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)

                # 데이터프레임 표시 (다중 선택 활성화)
                selection = st.dataframe(
                    df_del,
                    column_config={
                        "id": None, # ID 숨김
                        "order_no": "발주번호", "date": "접수일", "customer": "발주처",
                        "name": "제품명", "stock": "수량", "status": "상태"
                    },
                    column_order=["order_no", "date", "customer", "name", "stock", "status"],
                    hide_index=True,
                    width="stretch",
                    on_select="rerun",
                    selection_mode="multi-row",
                    key=f"del_orders_selection_{st.session_state['del_orders_key']}"
                )
                
                # 선택된 행 삭제 처리
                if selection.selection.rows:
                    selected_indices = selection.selection.rows
                    selected_rows = df_del.iloc[selected_indices]
                    
                    if st.button(f"🗑️ 선택한 {len(selected_rows)}건 영구 삭제", type="primary"):
                        for idx, row in selected_rows.iterrows():
                            db.collection("orders").document(row['id']).delete()
                        st.success(f"{len(selected_rows)}건이 삭제되었습니다.")
                        st.session_state["del_orders_key"] += 1
                        st.rerun()
            else:
                st.info("삭제할 발주 내역이 없습니다.")
            return

    st.write("조건을 설정하여 발주 내역을 조회하고 관리합니다.")

    # 메뉴 첫 진입 시 기본 검색 조건 설정
    if "search_performed" not in st.session_state:
        st.session_state["search_performed"] = True
        today = datetime.date.today()
        st.session_state["search_date_range"] = [today - datetime.timedelta(days=30), today]
        st.session_state["search_filter_status_single"] = "전체"
        st.session_state["search_criteria"] = "전체"
        st.session_state["search_keyword"] = ""

    with st.expander("검색", expanded=True):
        with st.form("search_form"):
            c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 2])
            # 날짜 범위 선택 (기본값: 세션에 저장된 값 사용)
            date_range = c1.date_input("조회 기간", st.session_state.get("search_date_range"), format="YYYY-MM-DD")
            # 상세 공정 상태 목록 추가
            status_options = ["전체", "발주접수", "제직대기", "제직중", "제직완료", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
            status_options = ["전체", "미출고(출고완료 제외)", "발주접수", "제직대기", "제직중", "제직완료", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
            
            # [수정] 상태 필터: 멀티셀렉트 -> 콤보박스(Selectbox)
            saved_status = st.session_state.get("search_filter_status_single", "전체")
            if saved_status not in status_options: saved_status = "전체"
            filter_status = c2.selectbox("진행 상태", status_options, index=status_options.index(saved_status))
            
            # [수정] 검색 조건: 콤보박스 + 텍스트 입력
            criteria_options = ["전체", "발주번호", "제품코드", "발주처", "제품명", "제품종류", "사종", "색상", "중량"]
            saved_criteria = st.session_state.get("search_criteria", "전체")
            if saved_criteria not in criteria_options: saved_criteria = "전체"
            
            search_criteria = c3.selectbox("검색 기준", criteria_options, index=criteria_options.index(saved_criteria))
            search_keyword = c4.text_input("검색어 입력", value=st.session_state.get("search_keyword", ""))
            
            c_b1, c_b2 = st.columns([1, 6])
            with c_b1:
                search_btn = st.form_submit_button("조회", use_container_width=True)

    # 검색 버튼 클릭 시 세션에 검색 조건 저장 (새로고침 되어도 유지되도록)
    if search_btn:
        st.session_state["search_performed"] = True
        st.session_state["search_date_range"] = date_range
        st.session_state["search_filter_status_single"] = filter_status
        st.session_state["search_criteria"] = search_criteria
        st.session_state["search_keyword"] = search_keyword
        st.rerun()

    if st.session_state.get("search_performed"):
        # 저장된 검색 조건 사용
        s_date_range = st.session_state["search_date_range"]
        
        # [NEW] 목록 갱신을 위한 키 초기화
        if "order_status_key" not in st.session_state:
            st.session_state["order_status_key"] = 0

        s_filter_status = st.session_state.get("search_filter_status_single", "전체")
        s_criteria = st.session_state.get("search_criteria", "전체")
        s_keyword = st.session_state.get("search_keyword", "")

        # 날짜 필터링을 위해 datetime 변환
        start_date = datetime.datetime.combine(s_date_range[0], datetime.time.min)
        end_date = datetime.datetime.combine(s_date_range[1], datetime.time.max) if len(s_date_range) > 1 else datetime.datetime.combine(s_date_range[0], datetime.time.max)

        docs = db.collection("orders").where("date", ">=", start_date).where("date", "<=", end_date).order_by("date", direction=firestore.Query.DESCENDING).stream()

    # 데이터를 리스트로 변환
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            
            # [수정] 마스터 완료 상태를 일반 '제직완료'로 표시
            if d.get('status') == "제직완료(Master)":
                d['status'] = "제직완료"
            
            if 'date' in d and d['date']:
                d['date'] = d['date'].strftime("%Y-%m-%d")
            rows.append(d)
            
        if rows:
            df = pd.DataFrame(rows)
            
            # [수정] 발주번호(order_no) 컬럼이 없으면 강제로 생성 (빈 값)
            if 'order_no' not in df.columns:
                df['order_no'] = ""
            
            # [NEW] order_type 컬럼 확인 및 초기화
            if 'order_type' not in df.columns:
                df['order_type'] = ""
            
            # [NEW] 납품요청일 날짜 포맷팅 (YYYY-MM-DD)
            if 'delivery_req_date' in df.columns:
                df['delivery_req_date'] = pd.to_datetime(df['delivery_req_date'], errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
            
            # [수정] 상태 필터 (단일 선택)
            if s_filter_status == "미출고(출고완료 제외)":
                df = df[df['status'] != '출고완료']
            elif s_filter_status != "전체":
                df = df[df['status'] == s_filter_status]
            
            # [수정] 검색어 필터 (기준에 따라)
            if s_keyword:
                s_keyword = s_keyword.lower()
                
                # [NEW] 다중 검색어 처리 (공백/콤마 구분, OR 조건)
                keywords = [k.strip() for k in re.split(r'[,\s]+', s_keyword) if k.strip()]
                
                if keywords:
                    # 정규식 패턴 생성 (k1|k2|...)
                    pattern = '|'.join([re.escape(k) for k in keywords])
                    
                    if s_criteria == "전체":
                        # 모든 컬럼 값을 문자열로 변환하여 검색 (정규식 사용)
                        mask = df.astype(str).apply(lambda x: ' '.join(x).lower(), axis=1).str.contains(pattern, regex=True, na=False)
                        df = df[mask]
                    else:
                        col_map_search = {"발주번호": "order_no", "제품코드": "product_code", "발주처": "customer", "제품명": "name", "제품종류": "product_type", "사종": "yarn_type", "색상": "color", "중량": "weight"}
                        target_col = col_map_search.get(s_criteria)
                        if target_col and target_col in df.columns:
                            df = df[df[target_col].astype(str).str.lower().str.contains(pattern, regex=True, na=False)]
            
            if df.empty:
                st.info("조건에 맞는 발주 내역이 없습니다.")
                return
            
            # 컬럼명 한글 매핑
            col_map = {
                "product_code": "제품코드", "order_no": "발주번호", "status": "상태", "date": "접수일", "order_type": "구분", "customer": "발주처",
                "name": "제품명", "product_type": "제품종류", "weaving_type": "제품종류(구)",
                "yarn_type": "사종", "color": "색상", "weight": "중량",
                "size": "사이즈", "stock": "수량",
                "delivery_req_date": "납품요청일", "delivery_to": "납품처",
                "delivery_contact": "납품연락처", "delivery_address": "납품주소",
                "note": "비고"
            }

            # 컬럼 순서 변경 (발주번호 -> 상태 -> 접수일 ...)
            display_cols = ["product_code", "order_no", "status", "date", "order_type", "customer", "name", "stock", "product_type", "weaving_type", "yarn_type", "color", "weight", "size", "delivery_req_date", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns] # 실제 존재하는 컬럼만 선택
            
            # 화면 표시용 데이터프레임 (한글 컬럼 적용)
            # [수정] id 컬럼을 포함하여 생성 (화면에는 숨김 처리 예정)
            cols_for_df = ['id'] + final_cols
            df_display = df[cols_for_df].rename(columns=col_map)
            
            # [수정] id 컬럼을 포함하여 생성 (화면에는 숨김 처리 예정)
            cols_for_df = ['id'] + final_cols
            df_display = df[cols_for_df].rename(columns=col_map)
            
            # [수정] NaN/NaT 및 문자열 "nan", "None" 등을 빈 문자열로 변환
            df_display = df_display.fillna("")
            df_display = df_display.replace(["nan", "None", "NaT"], "")
            
            # [NEW] 테이블 위 작업 영역 (상태변경, 수정버튼 등)
            action_placeholder = st.container()

            # [NEW] 모드 선택 (단일 선택 vs 다중 선택)
            # 파트너 계정은 일괄 제직 지시 기능 숨김
            if st.session_state.get("role") != "partner":
                c_mode, c_dummy = st.columns([2.5, 7.5])
                with c_mode:
                    multi_select_mode = st.toggle("✅ 제직건 선택(발주접수건 보기)", key="order_multi_mode")
            else:
                multi_select_mode = False

            # 모드에 따른 데이터 및 설정 조정
            if multi_select_mode:
                sel_mode = "multi-row"
                # 발주접수 상태만 필터링 (컬럼명이 한글로 변경되었으므로 매핑된 이름 사용)
                status_col = col_map.get("status", "상태")
                if status_col in df_display.columns:
                    df_display_view = df_display[df_display[status_col] == '발주접수']
                else:
                    df_display_view = df_display
                st.info("💡 '발주접수' 상태인 항목만 표시됩니다. 체크하여 일괄로 '제직대기' 처리하세요.")
            else:
                sel_mode = "single-row"
                df_display_view = df_display
                st.write("🔽 목록에서 항목을 선택하면 하단에 상세 정보가 표시됩니다.")
            
            # [NEW] 동적 높이 계산 (행당 약 35px, 최대 20행 700px)
            table_height = min((len(df_display_view) + 1) * 35 + 3, 700)
            
            selection = st.dataframe(
                df_display_view, 
                width="stretch", 
                hide_index=True,  # 맨 왼쪽 순번(0,1,2..) 숨기기
                column_config={"id": None}, # [NEW] id 컬럼 숨김
                on_select="rerun", # 선택 시 리런
                selection_mode=sel_mode, # [수정] 모드에 따라 변경
                height=table_height, # [수정] 목록 높이 동적 적용
                key=f"order_status_list_{st.session_state['order_status_key']}_{multi_select_mode}" # [수정] 동적 키 적용
            )
            
            if df_display_view.empty:
                st.markdown("<br>", unsafe_allow_html=True)

            # [MOVED] 작업 영역 로직 (테이블 상단)
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                # [수정] 화면에 보이는 데이터프레임 기준 선택
                selected_rows = df_display_view.iloc[selected_indices]
                
                # 1. 일괄 제직 지시 모드일 때
                if multi_select_mode:
                    with action_placeholder:
                        if not selected_rows.empty:
                            with st.expander(f"🚀 제직 지시 ({len(selected_rows)}건)", expanded=True):
                                st.write(f"선택한 **{len(selected_rows)}건**을 **'제직대기'**로 변경합니다.")
                                if st.button("선택 항목 제직대기로 발송", type="primary", key="btn_batch_weaving"):
                                    for idx, row in selected_rows.iterrows():
                                        db.collection("orders").document(row['id']).update({"status": "제직대기"})
                                    st.success(f"{len(selected_rows)}건이 제직대기 상태로 변경되었습니다.")
                                    st.session_state["order_status_key"] += 1
                                    st.rerun()
                
                # 2. 상세 수정 바로가기 (단일 선택 시)
                elif len(selection.selection.rows) == 1:
                    with action_placeholder:
                        st.markdown("""
                            <a href="#edit_detail_section" style="text-decoration: none;">
                                <div style="
                                    display: inline-block;
                                    padding: 0.5rem 1rem;
                                    background-color: #f0f2f6;
                                    color: #31333F;
                                    border-radius: 0.5rem;
                                    border: 1px solid #d6d6d8;
                                    font-weight: 500;
                                    text-align: center;
                                    cursor: pointer;
                                    margin-bottom: 10px;
                                ">
                                    선택한 내역 상세 수정 (화면 아래로 이동)
                                </div>
                            </a>
                        """, unsafe_allow_html=True)

            st.divider()

            # 인쇄 옵션 설정
            with st.expander("인쇄 옵션 설정"):
                # [NEW] 인쇄 옵션 저장 콜백
                def save_print_opts():
                    opts = {k: st.session_state[k] for k in print_options_keys}
                    save_user_settings(user_id, "order_print_opts", opts)

                po_c1, po_c2, po_c3, po_c4 = st.columns(4)
                p_title = po_c1.text_input("제목", key="os_p_title", on_change=save_print_opts)
                p_title_size = po_c2.number_input("제목 크기(px)", step=1, key="os_p_ts", on_change=save_print_opts)
                p_body_size = po_c3.number_input("본문 글자 크기(px)", step=1, key="os_p_bs", on_change=save_print_opts)
                p_padding = po_c4.number_input("셀 여백(px)", step=1, key="os_p_pad", on_change=save_print_opts)
                
                po_c5, po_c6, po_c7 = st.columns(3)
                p_show_date = po_c5.checkbox("출력일시 표시", key="os_p_sd", on_change=save_print_opts)
                p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], key="os_p_dp", on_change=save_print_opts)
                p_date_size = po_c7.number_input("일시 글자 크기(px)", step=1, key="os_p_ds", on_change=save_print_opts)
                
                st.caption("페이지 여백 (mm)")
                po_c8, po_c9, po_c10, po_c11 = st.columns(4)
                p_m_top = po_c8.number_input("상단", step=1, key="os_p_mt", on_change=save_print_opts)
                p_m_bottom = po_c9.number_input("하단", step=1, key="os_p_mb", on_change=save_print_opts)
                p_m_left = po_c10.number_input("좌측", step=1, key="os_p_ml", on_change=save_print_opts)
                p_m_right = po_c11.number_input("우측", step=1, key="os_p_mr", on_change=save_print_opts)
                
                po_c12, po_c13 = st.columns(2)
                os_p_bo = po_c12.number_input("외곽선 굵기", value=1.0, step=0.1, format="%.1f", key="os_p_bo", on_change=save_print_opts)
                os_p_bi = po_c13.number_input("안쪽선 굵기", value=0.5, step=0.1, format="%.1f", key="os_p_bi", on_change=save_print_opts)
                
                st.divider()
                st.markdown("###### 컬럼 설정 (출력 여부, 순서, 너비)")
                st.caption("💡 출력할 컬럼을 선택하고, 아래에서 순서와 너비를 조정하세요.")

                # [수정] 1. 출력 여부 및 순서 설정 (st.multiselect + 순서 변경 버튼)
                final_cols_kr = [col_map.get(c, c) for c in final_cols]

                # 세션에서 현재 선택된 컬럼 목록 가져오기 (순서 유지)
                if "os_p_selected_cols" not in st.session_state:
                    st.session_state["os_p_selected_cols"] = load_user_settings(user_id, "order_cols", final_cols_kr.copy())

                # 현재 데이터에 없는 컬럼은 선택 목록에서 제거
                st.session_state["os_p_selected_cols"] = [c for c in st.session_state["os_p_selected_cols"] if c in final_cols_kr]
                
                # 새로 추가된 컬럼은 목록 뒤에 추가
                new_cols = [c for c in final_cols_kr if c not in st.session_state["os_p_selected_cols"]]
                if new_cols:
                    st.session_state["os_p_selected_cols"].extend(new_cols)

                # [NEW] 컬럼 선택 저장 콜백
                def save_cols():
                    st.session_state["os_p_selected_cols"] = st.session_state["os_p_multiselect"]
                    save_user_settings(user_id, "order_cols", st.session_state["os_p_selected_cols"])

                # 멀티셀렉트로 출력 여부 결정
                selected_cols = st.multiselect(
                    "출력할 컬럼 선택",
                    options=final_cols_kr,
                    default=st.session_state["os_p_selected_cols"],
                    key="os_p_multiselect",
                    on_change=save_cols
                )
                # 변경사항을 즉시 세션에 반영
                st.session_state["os_p_selected_cols"] = selected_cols

                # 순서 변경 도구
                c_move1, c_move2, c_move3, c_move4 = st.columns([3, 1.3, 1.3, 2.6])
                
                target_col = c_move1.selectbox("이동할 컬럼 선택", selected_cols, label_visibility="collapsed", key="os_sb_col_move")

                if c_move2.button("⬆️ 위로", help="위로 이동", key="os_btn_up"):
                    if target_col and target_col in selected_cols:
                        idx = selected_cols.index(target_col)
                        if idx > 0:
                            selected_cols.pop(idx)
                            selected_cols.insert(idx - 1, target_col)
                            st.session_state["os_p_selected_cols"] = selected_cols
                            save_user_settings(user_id, "order_cols", selected_cols) # [NEW] 저장
                            st.rerun()

                if c_move3.button("⬇️ 아래로", help="아래로 이동", key="os_btn_down"):
                    if target_col and target_col in selected_cols:
                        idx = selected_cols.index(target_col)
                        if idx < len(selected_cols) - 1:
                            selected_cols.pop(idx)
                            selected_cols.insert(idx + 1, target_col)
                            st.session_state["os_p_selected_cols"] = selected_cols
                            save_user_settings(user_id, "order_cols", selected_cols) # [NEW] 저장
                            st.rerun()
                
                if c_move4.button("🔄 순서 초기화", help="기본 순서로 되돌립니다.", key="os_btn_reset"):
                    st.session_state["os_p_selected_cols"] = final_cols_kr.copy()
                    save_user_settings(user_id, "order_cols", st.session_state["os_p_selected_cols"]) # [NEW] 저장
                    st.rerun()

                # [수정] 2. 너비 설정 (Hybrid Slider)
                if "os_p_widths" not in st.session_state:
                    st.session_state["os_p_widths"] = load_user_settings(user_id, "order_widths", {})

                st.markdown("###### 컬럼 너비 설정 (비율 %)")
                use_custom_widths = st.checkbox("사용자 정의 너비 사용", value=bool(st.session_state["os_p_widths"]), key="os_ucw")

                if use_custom_widths:
                    # 컬럼 변경 시 초기화 (균등 분배)
                    current_widths = st.session_state["os_p_widths"]
                    # 기존 값이 픽셀 단위(>100)이거나 컬럼이 다르면 리셋
                    is_pixel_values = any(v > 100 for v in current_widths.values())
                    
                    if set(current_widths.keys()) != set(selected_cols) or is_pixel_values:
                        cnt = len(selected_cols)
                        if cnt > 0:
                            avg = 100 // cnt
                            rem = 100 % cnt
                            new_widths = {col: avg for col in selected_cols}
                            new_widths[selected_cols[-1]] += rem
                            st.session_state["os_p_widths"] = new_widths
                        else:
                            st.session_state["os_p_widths"] = {}

                    total_width = 0
                    for col in selected_cols:
                        c_name, c_slider, c_num = st.columns([2, 4, 1.5], vertical_alignment="center")
                        c_name.markdown(f"<span style='font-size:0.9em'>{col}</span>", unsafe_allow_html=True)
                        
                        val = st.session_state["os_p_widths"].get(col, 0)
                        k_s = f"os_s_{col}"
                        k_n = f"os_n_{col}"
                        
                        def on_chg_s(c=col, k=k_s): st.session_state["os_p_widths"][c] = st.session_state[k]
                        def on_chg_n(c=col, k=k_n): st.session_state["os_p_widths"][c] = st.session_state[k]

                        val_s = c_slider.slider("W", 0, 100, value=int(val), step=1, key=k_s, label_visibility="collapsed", on_change=on_chg_s)
                        val_n = c_num.number_input("W", 0, 100, value=int(val), step=1, key=k_n, label_visibility="collapsed", on_change=on_chg_n)
                        
                        total_width += val
                    
                    if total_width != 100:
                        st.warning(f"⚠️ 합계: {total_width}% (100%가 되도록 조정해주세요)")
                    else:
                        st.success("✅ 합계: 100%")
                    
                    save_user_settings(user_id, "order_widths", st.session_state["os_p_widths"])
                else:
                    st.session_state["os_p_widths"] = {}
                    save_user_settings(user_id, "order_widths", {})
                
                p_nowrap = st.checkbox("텍스트 줄바꿈 방지 (한 줄 표시)", key="os_p_nowrap", on_change=save_print_opts)

            # 엑셀 다운로드 및 인쇄 버튼
            c_btn_xls, c_btn_gap, c_btn_prt = st.columns([1.5, 5, 1.5])

            with c_btn_xls:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_display.to_excel(writer, index=False)
                
                st.download_button(
                    label="💾 엑셀 다운로드",
                    data=buffer.getvalue(),
                    file_name='발주현황.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    use_container_width=True
                )

            with c_btn_prt:
                if st.button("🖨️ 인쇄하기", use_container_width=True):
                    print_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    date_align = p_date_pos.lower()
                    date_display = "block" if p_show_date else "none"

                    # [수정] 인쇄 로직에 사용할 변수 추출
                    p_selected_cols = st.session_state.get("os_p_selected_cols", [])
                    p_widths = st.session_state.get("os_p_widths", {})
                    
                    # 인쇄용 데이터프레임 준비
                    if p_selected_cols:
                        valid_cols = [c for c in p_selected_cols if c in df_display.columns]
                        print_df = df_display[valid_cols]
                    else:
                        print_df = df_display

                    # CSS 생성 (줄바꿈 방지 및 너비 지정)
                    custom_css = ""
                    if p_nowrap:
                        custom_css += "td { white-space: nowrap; }\n"
                    
                    for i, col in enumerate(p_selected_cols):
                        w = p_widths.get(col, 0)
                        if w > 0:
                            # nth-child는 1부터 시작
                            custom_css += f"table tr th:nth-child({i+1}), table tr td:nth-child({i+1}) {{ width: {w}%; }}\n"

                    # [수정] body에 onload를 추가하고, 화면에는 보이지 않도록 CSS 수정
                    print_html = f"""
                        <html>
                        <head>
                            <title>{p_title}</title>
                            <style>
                                @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                                h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                                .info {{ text-align: {date_align}; font-size: {p_date_size}px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                                table {{ width: 100%; border-collapse: collapse; font-size: {p_body_size}px; border: {os_p_bo}px solid #444; }}
                                th, td {{ border: {os_p_bi}px solid #444; padding: {p_padding}px 4px; text-align: center; }}
                                th {{ background-color: #f0f0f0; font-weight: bold; }}
                                @media screen {{ body {{ display: none; }} }}
                                {custom_css}
                            </style>
                        </head>
                        <body onload="window.print();">
                            <h2>{p_title}</h2>
                            <div class="info">출력일시: {print_date}</div>
                            {print_df.to_html(index=False, border=1)}
                        </body>
                        </html>
                    """
                    # 보이지 않는 컴포넌트로 HTML을 렌더링하여 스크립트(window.print) 실행
                    st.components.v1.html(print_html, height=0, width=0)

            # --- 상세 수정 (단일 선택 시에만) ---
            if len(selection.selection.rows) == 1:
                # 스크롤 이동을 위한 앵커
                st.markdown('<div id="edit_detail_section"></div>', unsafe_allow_html=True)
                st.divider()
                
                selected_idx = selection.selection.rows[0]
                # 선택된 행의 데이터 가져오기 (df는 필터링된 상태일 수 있으므로 iloc 사용)
                sel_row = df.iloc[selected_idx]
                sel_id = sel_row['id']
                # [수정] 선택된 행의 ID를 이용해 원본 데이터(df)에서 행 찾기
                # (df_display_view는 한글 컬럼명이고 필터링되어 인덱스가 다를 수 있음)
                sel_id = selected_rows.iloc[0]['id']
                # 원본 df에서 해당 id를 가진 행 추출
                sel_row = df[df['id'] == sel_id].iloc[0]
                
                # 제직기 명칭 매핑을 위한 데이터 가져오기
                machine_map = {}
                try:
                    m_docs = db.collection("machines").stream()
                    for m in m_docs:
                        md = m.to_dict()
                        machine_map[md.get('machine_no')] = md.get('name')
                except: pass

                # [NEW] 상세 이력 뷰
                c_sub, c_close = st.columns([7.5, 1.5])
                with c_sub:
                    st.subheader(f"상세 이력 정보: {sel_row['name']} ({sel_row['order_no']})")
                with c_close:
                    if st.button("닫기", key="close_detail_view_os", use_container_width=True):
                        st.session_state["order_status_key"] += 1
                        st.rerun()
                
                def fmt_dt(val):
                    if pd.isna(val) or val == "" or val is None: return "-"
                    if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d %H:%M")
                    if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d %H:%M")
                    return str(val)[:16]
                
                def fmt_date(val):
                    if pd.isna(val) or val == "" or val is None: return "-"
                    if isinstance(val, pd.Timestamp): return val.strftime("%Y-%m-%d")
                    if isinstance(val, datetime.datetime): return val.strftime("%Y-%m-%d")
                    return str(val)[:10]

                def fmt_num(val, unit=""):
                    try: return f"{int(val):,}{unit}"
                    except: return "-"
                
                def fmt_float(val, unit=""):
                    try: return f"{float(val):,.1f}{unit}"
                    except: return "-"
                
                def fmt_money(val):
                    try: return f"{int(val):,}원"
                    except: return "-"

                # [NEW] 공정별 개별 테이블 표시
                
                # --- 1. 제직 공정 ---
                st.markdown("##### 제직 공정")
                weaving_data = []
                if sel_row.get('weaving_start_time'):
                    m_no = sel_row.get('machine_no')
                    try:
                        m_no_int = int(m_no) if pd.notna(m_no) else None
                        m_name = machine_map.get(m_no_int, f"{m_no_int}호기" if m_no_int is not None else "-")
                    except:
                        m_name = str(m_no)

                    w_status = "진행중"
                    if sel_row.get('weaving_end_time'):
                        w_status = "완료"
                    
                    weaving_data.append({
                        "상태": w_status,
                        "제직기": m_name,
                        "시작일시": fmt_dt(sel_row.get('weaving_start_time')),
                        "제직롤": fmt_num(sel_row.get('weaving_roll_count'), '롤'),
                        "완료일시": fmt_dt(sel_row.get('weaving_end_time')),
                        "생산매수": fmt_num(sel_row.get('real_stock'), '장'),
                        "생산중량": fmt_float(sel_row.get('prod_weight_kg'), 'kg'),
                        "평균중량": fmt_float(sel_row.get('avg_weight'), 'g')
                    })
                
                if weaving_data:
                    st.dataframe(pd.DataFrame(weaving_data), hide_index=True, use_container_width=True)
                else:
                    st.info("제직 공정 대기 중입니다.")

                # --- 2. 염색 공정 ---
                st.markdown("##### 염색 공정")
                dyeing_data = []
                if sel_row.get('dyeing_out_date'):
                    d_status = "진행중"
                    if sel_row.get('dyeing_in_date'):
                        d_status = "완료"
                    
                    cc = sel_row.get('dyeing_color_code')
                    color_info = f"{sel_row.get('dyeing_color_name', '')} {f'({cc})' if cc else ''}".strip()

                    dyeing_data.append({
                        "상태": d_status,
                        "염색업체": sel_row.get('dyeing_partner', '-'),
                        "출고일": fmt_date(sel_row.get('dyeing_out_date')),
                        "출고중량(kg)": fmt_float(sel_row.get('dyeing_out_weight')),
                        "입고일": fmt_date(sel_row.get('dyeing_in_date')),
                        "입고중량(kg)": fmt_float(sel_row.get('dyeing_in_weight')),
                        "색상": color_info,
                        "염색비용": fmt_money(sel_row.get('dyeing_amount'))
                    })

                if dyeing_data:
                    st.dataframe(pd.DataFrame(dyeing_data), hide_index=True, use_container_width=True)
                else:
                    st.info("염색 공정 대기 중입니다.")

                # --- 3. 봉제 공정 ---
                st.markdown("##### 봉제 공정")
                sewing_data = []
                if sel_row.get('sewing_start_date'):
                    s_status = "진행중"
                    if sel_row.get('sewing_end_date'):
                        s_status = "완료"
                    
                    sewing_data.append({
                        "상태": s_status,
                        "봉제업체": sel_row.get('sewing_partner', '-'),
                        "작업구분": sel_row.get('sewing_type', '-'),
                        "시작일": fmt_date(sel_row.get('sewing_start_date')),
                        "완료일": fmt_date(sel_row.get('sewing_end_date')),
                        "완료수량": fmt_num(sel_row.get('stock'), '장'),
                        "불량수량": fmt_num(sel_row.get('sewing_defect_qty'), '장'),
                        "봉제비용": fmt_money(sel_row.get('sewing_amount'))
                    })
                
                if sewing_data:
                    st.dataframe(pd.DataFrame(sewing_data), hide_index=True, use_container_width=True)
                else:
                    st.info("봉제 공정 대기 중입니다.")

                # --- 4. 출고 공정 ---
                st.markdown("##### 출고/배송")
                shipping_data = []
                if sel_row.get('shipping_date'):
                    shipping_data.append({
                        "상태": "완료",
                        "출고일시": fmt_dt(sel_row.get('shipping_date')),
                    })

                if shipping_data:
                    st.dataframe(pd.DataFrame(shipping_data), hide_index=True, use_container_width=True)
                else:
                    st.info("출고 대기 중입니다.")
                
                st.divider()
                
                # 수정 폼을 위해 기초 데이터 다시 로드
                product_types_coded = get_common_codes("product_types", [])
                product_type_names = [item['name'] for item in product_types_coded]
                customer_list = get_partners("발주처")

                with st.expander("발주 내역 상세 수정", expanded=False):
                    with st.form("edit_order_form"):
                        st.write(f"선택된 발주건: **{sel_row['customer']} - {sel_row['name']}**")
                        
                        # [추가] 상태 변경 기능 (관리자용 강제 변경)
                        st.markdown("##### 관리자 상태 변경 (실수 복구용)")
                        status_options = ["발주접수", "제직대기", "제직중", "제직완료", "염색출고", "염색중", "염색완료", "봉제중", "봉제완료", "출고완료"]
                        e_status = st.selectbox("현재 상태", status_options, index=status_options.index(sel_row['status']) if sel_row['status'] in status_options else 0)
                        st.divider()

                        # 모든 필드 수정 가능하도록 배치
                        ec1, ec2, ec3, ec4 = st.columns(4)
                        e_customer = ec1.selectbox("발주처", customer_list, index=customer_list.index(sel_row['customer']) if sel_row['customer'] in customer_list else 0)
                        
                        curr_type = sel_row.get('order_type', '')
                        type_opts = ["신규제직", "추가제직"]
                        e_order_type = ec2.selectbox("신규/추가 구분", type_opts, index=type_opts.index(curr_type) if curr_type in type_opts else 0)
                        
                        e_name = ec3.text_input("제품명", value=sel_row['name'])
                        e_stock = ec4.number_input("수량", value=int(sel_row['stock']), step=10)

                        ec5, ec6, ec7, ec8 = st.columns(4)
                        current_product_type = sel_row.get('product_type', sel_row.get('weaving_type'))
                        e_product_type = ec5.selectbox("제품종류", product_type_names, index=product_type_names.index(current_product_type) if current_product_type in product_type_names else 0)
                        e_yarn = ec6.text_input("사종", value=sel_row.get('yarn_type', ''))
                        e_color = ec7.text_input("색상", value=sel_row.get('color', ''))
                        e_weight = ec8.number_input("중량", value=int(sel_row.get('weight', 0)), step=10)

                        ec9, ec10, ec11 = st.columns(3)
                        e_size = ec9.text_input("사이즈", value=sel_row.get('size', ''))
                        
                        # [수정] 날짜 파싱 오류 방지 (시간 정보가 포함된 경우 처리)
                        try:
                            if sel_row.get('delivery_req_date'):
                                default_date = pd.to_datetime(str(sel_row['delivery_req_date'])).date()
                            else:
                                default_date = datetime.date.today()
                        except:
                            default_date = datetime.date.today()
                            
                        e_del_date = ec10.date_input("납품요청일", default_date, format="YYYY-MM-DD")
                        e_note = ec11.text_input("특이사항", value=sel_row.get('note', ''))
                        
                        ec12, ec13, ec14 = st.columns(3)
                        e_del_to = ec12.text_input("납품처", value=sel_row.get('delivery_to', ''))
                        e_del_contact = ec13.text_input("납품연락처", value=sel_row.get('delivery_contact', ''))
                        e_del_addr = ec14.text_input("납품주소", value=sel_row.get('delivery_address', ''))

                        if st.form_submit_button("수정 저장"):
                            db.collection("orders").document(sel_id).update({
                                "status": e_status, # 상태 변경 반영
                                "customer": e_customer,
                                "order_type": e_order_type,
                                "name": e_name,
                                "stock": e_stock,
                                "product_type": e_product_type,
                                "yarn_type": e_yarn,
                                "color": e_color,
                                "weight": e_weight,
                                "size": e_size,
                                "delivery_req_date": str(e_del_date),
                                "note": e_note,
                                "delivery_to": e_del_to,
                                "delivery_contact": e_del_contact,
                                "delivery_address": e_del_addr
                            })
                            st.success("수정되었습니다.")
                            st.session_state["order_status_key"] += 1
                            st.rerun()
                    
                    # 삭제 확인 및 처리 (폼 밖에서 처리)
                    st.divider()
                    if st.button("🗑️ 이 발주건 삭제", type="primary", key="btn_del_req"):
                        st.session_state["delete_confirm_id"] = sel_id
                    
                    if st.session_state.get("delete_confirm_id") == sel_id:
                        st.warning("정말로 삭제하시겠습니까? (복구 불가)")
                        col_conf1, col_conf2 = st.columns(2)
                        if col_conf1.button("✅ 예, 삭제합니다", key="btn_del_yes"):
                            db.collection("orders").document(sel_id).delete()
                            st.session_state["delete_confirm_id"] = None
                            st.success("삭제되었습니다.")
                            st.session_state["order_status_key"] += 1
                            st.rerun()
                        if col_conf2.button("❌ 취소", key="btn_del_no"):
                            st.session_state["delete_confirm_id"] = None
                            st.rerun()
            elif len(selection.selection.rows) > 1 and not multi_select_mode:
                st.info("ℹ️ 상세 수정은 한 번에 하나의 행만 선택했을 때 가능합니다. (상단 일괄 변경 기능 사용 가능)")
            elif not selection.selection.rows:
                st.info("👆 위 목록에서 수정하거나 상태를 변경할 행을 선택해주세요.")

        else:
            st.info("해당 기간에 조회된 데이터가 없습니다.")