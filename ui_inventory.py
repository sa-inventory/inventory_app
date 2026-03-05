import streamlit as st
import pandas as pd
import datetime
import io
import uuid
from firebase_admin import firestore
from utils import get_partners, get_common_codes, search_address_api, generate_report_html, save_user_settings, load_user_settings

# [NEW] 재고 현황 로직을 별도 함수로 분리 (출고 작업과 재고 현황에서 공유)
def render_inventory_logic(db, allow_shipping=False, key_prefix="inv"):
    # [NEW] 파트너 권한 확인
    user_role = st.session_state.get("role")
    linked_partner = st.session_state.get("linked_partner")
    is_partner = (user_role == "partner")
    user_id = st.session_state.get("user_id")

    # [NEW] 인쇄 설정 로드 및 초기화
    inv_print_defaults = {
        "inv_p_mode": "요약 목록", "inv_p_title": "재고 현황",
        "inv_p_ts": 24, "inv_p_fs": 12, "inv_p_pad": 5,
        "inv_p_date": True, "inv_p_total": True,
        "inv_p_mt": 15, "inv_p_mb": 15, "inv_p_ml": 15, "inv_p_mr": 15,
        "inv_p_bo": 1.0, "inv_p_bi": 0.5
    }
    
    saved_opts = load_user_settings(user_id, "inv_print_opts", {})
    
    for k, v in inv_print_defaults.items():
        wk = f"{k}_{allow_shipping}_{key_prefix}"
        if wk not in st.session_state:
            st.session_state[wk] = saved_opts.get(k, v)

    def save_inv_opts():
        current_opts = {}
        for k in inv_print_defaults.keys():
            wk = f"{k}_{allow_shipping}_{key_prefix}"
            current_opts[k] = st.session_state[wk]
        save_user_settings(user_id, "inv_print_opts", current_opts)

    # [NEW] 인쇄용 HTML 생성 함수 (우측 정렬 지원)
    def generate_inventory_report_html(title, df, summary_text, options, right_align_cols=[]):
        mt, mr, mb, ml = options.get('mt', 15), options.get('mr', 15), options.get('mb', 15), options.get('ml', 15)
        ts, bs, pad = options.get('ts', 24), options.get('bs', 11), options.get('pad', 6)
        da, ds, dd = options.get('da', 'right'), options.get('ds', 12), options.get('dd', 'block')
        bo, bi = options.get('bo', 1.0), options.get('bi', 0.5)
        
        print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        align_css = ""
        if right_align_cols:
            for col in right_align_cols:
                if col in df.columns:
                    idx = df.columns.get_loc(col) + 1
                    align_css += f"table tr td:nth-child({idx}) {{ text-align: right; }}\n"

        css = f"""@page {{ margin: {mt}mm {mr}mm {mb}mm {ml}mm; }} body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }} h2 {{ text-align: center; margin-bottom: 5px; font-size: {ts}px; }} .info {{ text-align: {da}; font-size: {ds}px; margin-bottom: 10px; color: #555; display: {dd}; }} table {{ width: 100%; border-collapse: collapse; font-size: {bs}px; border: {bo}px solid #444; }} th, td {{ border: {bi}px solid #444; padding: {pad}px 4px; text-align: center; }} th {{ background-color: #f0f0f0; }} .summary {{ text-align: right; margin-top: 10px; font-weight: bold; font-size: {bs}px; }} {align_css} @media screen {{ body {{ display: none; }} }}"""
        
        html = f"""<html><head><title>{title}</title><style>{css}</style></head><body onload="window.print()"><h2>{title}</h2><div class="info">출력일시: {print_now}</div>{df.to_html(index=False)}<div class="summary">{summary_text}</div></body></html>"""
        return html

    # [NEW] 주소 검색 모달 (Dialog) - 재고 출고용
    if f"show_inv_ship_addr_dialog_{key_prefix}" not in st.session_state:
        st.session_state[f"show_inv_ship_addr_dialog_{key_prefix}"] = False

    @st.dialog("주소 검색")
    def show_address_search_modal_inv_ship():
        if "is_addr_keyword" not in st.session_state: st.session_state.is_addr_keyword = ""
        if "is_addr_page" not in st.session_state: st.session_state.is_addr_page = 1

        with st.form(f"addr_search_form_inv_ship_{key_prefix}"):
            keyword_input = st.text_input("도로명 또는 지번 주소 입력", value=st.session_state.is_addr_keyword, placeholder="예: 세종대로 209")
            if st.form_submit_button("검색"):
                st.session_state.is_addr_keyword = keyword_input
                st.session_state.is_addr_page = 1
                st.rerun()

        if st.session_state.is_addr_keyword:
            results, common, error = search_address_api(st.session_state.is_addr_keyword, st.session_state.is_addr_page)
            if error: st.error(error)
            elif results:
                st.session_state['is_addr_results'] = results
                st.session_state['is_addr_common'] = common
            else: st.warning("검색 결과가 없습니다.")
        
        if 'is_addr_results' in st.session_state:
            for idx, item in enumerate(st.session_state['is_addr_results']):
                road = item['roadAddr']
                zip_no = item['zipNo']
                full_addr = f"({zip_no}) {road}"
                if st.button(f"{full_addr}", key=f"sel_is_{zip_no}_{idx}_{key_prefix}"):
                    st.session_state[f"inv_ship_addr_input_{key_prefix}"] = full_addr
                    st.session_state[f"show_inv_ship_addr_dialog_{key_prefix}"] = False
                    for k in ['is_addr_keyword', 'is_addr_page', 'is_addr_results', 'is_addr_common']:
                        if k in st.session_state: del st.session_state[k]
                    st.rerun()
            
            # Pagination
            common_info = st.session_state.get('is_addr_common', {})
            if common_info:
                total_count = int(common_info.get('totalCount', 0))
                current_page = int(common_info.get('currentPage', 1))
                count_per_page = int(common_info.get('countPerPage', 10))
                total_pages = (total_count + count_per_page - 1) // count_per_page if total_count > 0 else 1
                
                if total_pages > 1:
                    st.divider()
                    p_cols = st.columns([1, 2, 1])
                    if p_cols[0].button("◀ 이전", disabled=(current_page <= 1), key=f"is_prev_{key_prefix}"):
                        st.session_state.is_addr_page -= 1
                        st.rerun()
                    p_cols[1].write(f"페이지 {current_page} / {total_pages}")
                    if p_cols[2].button("다음 ▶", disabled=(current_page >= total_pages), key=f"is_next_{key_prefix}"):
                        st.session_state.is_addr_page += 1
                        st.rerun()

        st.divider()
        if st.button("닫기", key=f"close_addr_inv_ship_{key_prefix}", use_container_width=True):
            st.session_state[f"show_inv_ship_addr_dialog_{key_prefix}"] = False
            st.rerun()

    # [NEW] 스마트 데이터 에디터 - 1. 변경사항 검토 및 확정 UI
    changes_key = f'inventory_changes_{allow_shipping}_{key_prefix}'
    if st.session_state.get(changes_key):
        changes = st.session_state[changes_key]
        st.divider()
        st.subheader("📝 변경사항 검토")
        st.warning("아래 변경사항을 확인하고 확정 버튼을 눌러주세요.")
        st.warning("변경된 셀은 노란색으로 표시됩니다. 내용을 확인하고 확정 버튼을 눌러주세요.")
        
        for change in changes:
            st.markdown(f"**- 제품명: {change['name']}** (ID: `{change['id']}`)")
            change_details = change['changes']
            if 'stock' in change_details:
                before, after = change_details['stock']
                st.markdown(f"  - **재고수량**: `{before:,}` → `{after:,}`")
            if 'shipping_unit_price' in change_details:
                before, after = change_details['shipping_unit_price']
                st.markdown(f"  - **단가**: `{before:,}` → `{after:,}`")
        # [NEW] 변경 내역 DataFrame 생성 및 스타일링
        display_rows = []
        for c in changes:
            # row_data가 없으면(구버전 세션 등) 기본값 처리
            row = c.get('row_data', {'제품명': c['name'], '구분/발주처': '-', '재고수량': 0, '단가': 0}).copy()
            row['_id'] = c['id']
            display_rows.append(row)
            
        if display_rows:
            df_review = pd.DataFrame(display_rows)
            
            def highlight_changes(row):
                styles = [''] * len(row)
                c_info = next((x for x in changes if x['id'] == row['_id']), None)
                if c_info:
                    changed_fields = c_info['changes']
                    # 필드명과 컬럼명 매핑
                    field_map = {'stock': '재고수량', 'shipping_unit_price': '단가'}
                    
                    for field, col_name in field_map.items():
                        if field in changed_fields:
                            try:
                                idx = row.index.get_loc(col_name)
                                styles[idx] = 'background-color: #fff3cd; color: #856404; font-weight: bold;'
                            except: pass
                return styles

            st.dataframe(
                df_review.drop(columns=['_id']).style.apply(highlight_changes, axis=1),
                hide_index=True,
                use_container_width=True
            )
        
        c1, c2, c3 = st.columns([1.2, 1, 5])
        if c1.button("✅ 변경 확정", type="primary", key=f"confirm_inv_changes_{allow_shipping}_{key_prefix}"):
            # Firestore에 변경사항 업데이트
            for change in changes:
                doc_id = change['id']
                update_data = {}
                if 'stock' in change['changes']:
                    update_data['stock'] = change['changes']['stock'][1]
                if 'shipping_unit_price' in change['changes']:
                    update_data['shipping_unit_price'] = change['changes']['shipping_unit_price'][1]
                
                if update_data:
                    db.collection("orders").document(doc_id).update(update_data)
            
            st.success(f"{len(changes)}건의 재고 정보가 수정되었습니다.")
            del st.session_state[changes_key]
            st.rerun()
            
        if c2.button("❌ 취소", key=f"cancel_inv_changes_{allow_shipping}_{key_prefix}"):
            del st.session_state[changes_key]
            st.rerun()
        
        st.stop() # 검토 중에는 아래 UI를 그리지 않음

    # 재고 기준: status == "봉제완료" (출고 전 단계)
    docs = db.collection("orders").where("status", "==", "봉제완료").stream()
    rows = []
    for doc in docs:
        d = doc.to_dict()
        
        # [NEW] 파트너인 경우 본인 데이터만 필터링
        if is_partner and linked_partner:
            if d.get("customer") != linked_partner: continue
            
        d['id'] = doc.id
        rows.append(d)

    if rows:
        df = pd.DataFrame(rows)
        
        # 상단: 제품별 재고 요약
        st.subheader("제품별 재고")
        
        ensure_cols = ['product_code', 'name', 'product_type', 'yarn_type', 'weight', 'size', 'stock', 'shipping_unit_price']
        for c in ensure_cols:
            if c not in df.columns:
                if c in ['stock', 'weight', 'shipping_unit_price']:
                    df[c] = 0
                else:
                    df[c] = ""
        
        df['stock'] = pd.to_numeric(df['stock'], errors='coerce').fillna(0).astype(int)
        df['weight'] = pd.to_numeric(df['weight'], errors='coerce').fillna(0).astype(int)
        df['shipping_unit_price'] = pd.to_numeric(df['shipping_unit_price'], errors='coerce').fillna(0).astype(int)

        # [NEW] 총 재고 금액 계산
        df['total_value'] = df['stock'] * df['shipping_unit_price']

        # [NEW] 간편 검색 기능 (사용자 요청 반영)
        with st.expander("검색", expanded=True):
            c_search1, c_search2 = st.columns([1, 3])
            search_criteria = c_search1.selectbox("검색 기준", ["전체(통합)", "제품코드", "발주처", "제품종류", "제품명"], key=f"inv_search_criteria_{allow_shipping}_{key_prefix}")
            search_keyword = c_search2.text_input("검색어 입력", key=f"inv_search_keyword_{allow_shipping}_{key_prefix}")
            
            if search_keyword:
                search_keyword = search_keyword.lower()
                if search_criteria == "전체(통합)":
                    mask = df.apply(lambda x: search_keyword in str(x.get('product_code', '')).lower() or
                                              search_keyword in str(x.get('customer', '')).lower() or
                                              search_keyword in str(x.get('product_type', '')).lower() or
                                              search_keyword in str(x.get('name', '')).lower() or
                                              search_keyword in str(x.get('note', '')).lower() or
                                              search_keyword in str(x.get('order_no', '')).lower(), axis=1)
                    df = df[mask]
                elif search_criteria == "제품코드":
                    df = df[df['product_code'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "발주처":
                    df = df[df['customer'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품종류":
                    df = df[df['product_type'].astype(str).str.lower().str.contains(search_keyword, na=False)]
                elif search_criteria == "제품명":
                    df = df[df['name'].astype(str).str.lower().str.contains(search_keyword, na=False)]

        # [NEW] 기본 정렬 설정: 제품코드(오름차순) -> 제품명(오름차순)
        sort_cols = []
        if 'product_code' in df.columns: sort_cols.append('product_code')
        if 'name' in df.columns: sort_cols.append('name')
        if sort_cols:
            df = df.sort_values(by=sort_cols, ascending=[True] * len(sort_cols))
        
        # [NEW] 조회 방식 선택 (요약 vs 전체 리스트)
        if is_partner:
            view_mode = "제품명 보기(제품코드별 상세품목)"
            # [FIX] 파트너는 탭 없이 전체 목록만 표시 (UnboundLocalError 방지)
            tab1 = None
            tab2 = st.container()
        else:
            # [수정] 탭 방식으로 변경 (사용자 요청 반영)
            # 탭 스타일링 (글자 크기 확대 및 굵게)
            st.markdown("""
            <style>
                button[data-baseweb="tab"] div p {
                    font-size: 1.2rem !important;
                    font-weight: bold !important;
                }
            </style>
            """, unsafe_allow_html=True)

            tab1, tab2 = st.tabs(["제품코드별 보기", "제품명별 보기(상세정보)"])
            
            # 탭 선택에 따라 view_mode 설정 (실제 렌더링은 아래 if문에서 분기)
            # st.tabs는 컨테이너 역할만 하므로, 현재 활성화된 탭을 알기 위해선
            # 각 탭 내부에서 내용을 그리거나, 별도의 상태 관리가 필요하지 않음 (순차 실행)
            # 여기서는 구조상 view_mode 변수를 설정하고 아래 로직을 태우기 위해
            # 탭 내부가 아닌 외부 변수로 제어하려 했으나, st.tabs는 UI 컨테이너이므로
            # 탭 내부에서 각각 렌더링 로직을 호출하거나, 탭 선택 상태를 알 수 있는 방법이 제한적임.
            # 따라서, 아래의 if view_mode == ... 로직을 각 탭 내부로 이동시키는 것이 가장 깔끔함.
            
            # 하지만 기존 로직(if view_mode == ...)이 길어서 이동 시 코드 중복이나 복잡도가 증가할 수 있음.
            # 여기서는 탭 내부에서 view_mode를 강제로 지정하여 아래 로직이 실행되도록 구조를 변경함.
            
            # [중요] st.tabs는 클릭 시 리런되지 않음. 
            # 따라서 탭 내부에서 내용을 직접 그려야 함.
            
            # 공통 로직(데이터 준비 등)은 위에서 이미 수행됨.
            
            # 탭 1: 제품코드별 보기
            with tab1:
                view_mode = "제품코드 보기"
                # 아래 로직이 view_mode 변수에 의존하므로, 여기서 바로 그리지 않고
                # view_mode 변수만 설정하면 탭 밖에서 그려질 것 같지만,
                # st.tabs는 컨테이너라 탭 밖의 내용은 탭과 무관하게 그려짐 (탭 아래에 그려짐).
                # 즉, 탭을 누르면 해당 탭 내용만 보여야 하는데, 
                # 기존 코드는 view_mode 변수 하나로 전체 화면을 제어하고 있었음.
                
                # 해결책: 기존의 if view_mode == ... else ... 로직을 함수화하거나
                # 각 탭 안으로 코드를 이동시켜야 함.
                # 여기서는 코드 이동 방식을 선택 (가장 직관적)
                pass # 아래에서 처리

            with tab2:
                view_mode = "제품명 보기(제품코드별 상세품목)"
                pass # 아래에서 처리

        # [MOVED] 요약 데이터 계산 (필터링 후)
        summary = df.groupby('product_code').agg({
            'product_type': 'first',
            'yarn_type': 'first',
            'weight': 'first',
            'size': 'first',
            'stock': 'sum',
            'shipping_unit_price': 'mean',
            'total_value': 'sum'
        }).reset_index()
        
        summary['shipping_unit_price'] = summary['shipping_unit_price'].astype(int)
        
        summary_cols = {
            'product_code': '제품코드', 'product_type': '제품종류',
            'yarn_type': '사종', 'weight': '중량', 'size': '사이즈',
            'stock': '재고수량', 'shipping_unit_price': '평균단가',
            'total_value': '총재고금액'
        }
        
        disp_cols = ['product_code', 'product_type', 'yarn_type', 'weight', 'size', 'shipping_unit_price', 'stock', 'total_value']

        # [MOVED] 인쇄 및 엑셀 내보내기 설정 (공통 영역으로 이동)
        # 데이터 준비 (공통)
        df_detail_print = df.copy()
        if 'date' in df_detail_print.columns:
            df_detail_print['date'] = df_detail_print['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
        
        # 상세 내역에 표시할 컬럼 정의 (모든 컬럼 포함)
        detail_col_map = {
            "product_code": "제품코드", "customer": "구분/발주처", "name": "제품명", 
            "product_type": "제품종류", "yarn_type": "사종", "weight": "중량", 
            "size": "사이즈", "color": "색상", "shipping_unit_price": "단가", 
            "stock": "재고수량", "order_no": "발주번호", "date": "등록/접수일", "note": "비고",
            "delivery_req_date": "납품요청일", "delivery_to": "납품처"
        }
        detail_cols = [c for c in detail_col_map.keys() if c in df_detail_print.columns]
        df_detail_final = df_detail_print[detail_cols].rename(columns=detail_col_map)

        # [수정] 구분선 간격 조정 (좁게)
        st.markdown("<hr style='margin: 10px 0; border: none; border-top: 1px solid #e6e6e6;'>", unsafe_allow_html=True)

        # [NEW] 선택된 행을 저장할 변수 (출고용)
        selected_rows_for_shipping = None

        # 관리자 권한 확인 (삭제 기능용)
        is_admin = st.session_state.get("role") == "admin"
        # [FIX] can_edit 변수 정의 위치 이동 (UnboundLocalError 방지)
        can_edit = is_admin and not allow_shipping


        # [수정] 탭 내부로 로직 이동
        # 탭 1 내용
        if tab1: # [FIX] 파트너인 경우 tab1이 None이므로 실행되지 않음
            with tab1:
                # [NEW] 테이블 우측 상단에 '모든 품목 조회' 체크박스 배치 (탭 내부로 이동)
                c_h1, c_h2 = st.columns([7.5, 2.5])
                with c_h1:
                     st.write("🔽 상세 내역을 확인할 제품을 선택하세요.")
                with c_h2:
                    stock_filter_opt_1 = st.radio("조회 옵션", ["전체코드보기", "재고있는 품목보기"], index=0, horizontal=True, label_visibility="collapsed", key=f"inv_stock_filter_1_{allow_shipping}_{key_prefix}")

                # [NEW] 재고 필터 적용 (탭별 독립 적용)
                summary_view = summary.copy()
                if stock_filter_opt_1 == "재고있는 품목보기":
                    summary_view = summary_view[summary_view['stock'] > 0]

                # [MOVED] 스마트 데이터 에디터 - 2. 수정 모드 토글 (테이블 좌측 상단으로 이동 - 탭 내부)
                can_edit = is_admin and not allow_shipping
                edit_mode_t1 = False
                if can_edit:
                    # [수정] 토글 스위치 배치 (좌측 정렬)
                    c_toggle, _ = st.columns([2, 8])
                    edit_mode_t1 = c_toggle.toggle("재고 수정 모드", help="활성화하면 목록에서 수량과 단가를 직접 수정할 수 있습니다.", key=f"edit_mode_{allow_shipping}_{key_prefix}")

                # [수정] 동적 높이 계산 (행당 약 35px, 최대 20행 700px)
                summary_height = min((len(summary_view) + 1) * 35 + 3, 700)
                
                selection_summary = st.dataframe(
                    summary_view[disp_cols].rename(columns=summary_cols),
                    width="stretch",
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    height=summary_height,
                    key=f"inv_summary_list_{allow_shipping}_{key_prefix}"
                )
                
                # [NEW] 제품별 요약 목록 합계 표시
                st.markdown(f"<div style='text-align:right; font-weight:bold; padding:5px; color:#333;'>총 재고수량 합계: {summary_view['stock'].sum():,}</div>", unsafe_allow_html=True)

                if selection_summary.selection.rows:
                    idx = selection_summary.selection.rows[0]
                    sel_p_code = summary_view.iloc[idx]['product_code']
                    
                    st.divider()
                    st.markdown(f"### 상세 재고 내역: **{sel_p_code}**")
                    
                    detail_df = df[df['product_code'] == sel_p_code].copy()
                    
                    if 'date' in detail_df.columns:
                        detail_df['date'] = detail_df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
                    
                    # [NEW] 임의 등록 재고 발주번호 마스킹
                    if 'order_no' in detail_df.columns:
                        detail_df['order_no'] = detail_df['order_no'].apply(lambda x: '-' if str(x).startswith('STOCK-') else x)

                    # [NEW] 스마트 데이터 에디터 - 3. 수정 모드 분기
                    if edit_mode_t1:
                        st.info("수정할 셀을 더블클릭하여 값을 변경한 후, 하단의 '변경사항 저장' 버튼을 누르세요.")
                        
                        detail_cols_for_editor = ["id", "customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                        for c in detail_cols_for_editor:
                            if c not in detail_df.columns: detail_df[c] = ""

                        edited_df = st.data_editor(
                            detail_df,
                            column_config={
                                "id": None, "customer": st.column_config.TextColumn("구분/발주처", disabled=True),
                                "name": st.column_config.TextColumn("제품명", disabled=True),
                                "product_type": st.column_config.TextColumn("제품종류", disabled=True),
                                "yarn_type": st.column_config.TextColumn("사종", disabled=True),
                                "weight": st.column_config.TextColumn("중량", disabled=True),
                                "size": st.column_config.TextColumn("사이즈", disabled=True),
                                "color": st.column_config.TextColumn("색상", disabled=True),
                                "shipping_unit_price": st.column_config.NumberColumn("단가", format="%d"),
                                "stock": st.column_config.NumberColumn("재고수량", format="%d"),
                                "order_no": st.column_config.TextColumn("발주번호", disabled=True),
                                "date": st.column_config.TextColumn("등록/접수일", disabled=True),
                                "note": st.column_config.TextColumn("비고", disabled=True),
                            },
                            column_order=detail_cols_for_editor,
                            hide_index=True, height=min((len(detail_df) + 1) * 35 + 3, 600),
                            key=f"inv_editor_detail_{sel_p_code}_{key_prefix}"
                        )

                        original_df_subset = detail_df.reset_index(drop=True)
                        edited_df_reset = edited_df.reset_index(drop=True)
                        changed_mask = (original_df_subset.ne(edited_df_reset)).any(axis=1)

                        if changed_mask.any():
                            if st.button("변경사항 저장", key=f"save_changes_detail_{sel_p_code}_{key_prefix}", type="primary"):
                                changed_rows = edited_df_reset[changed_mask]
                                original_changed_rows = original_df_subset[changed_mask]
                                
                                change_list = []
                                for i in changed_rows.index:
                                    original_row = original_changed_rows.loc[i]
                                    edited_row = changed_rows.loc[i]
                                    
                                    change_item = {'id': original_row['id'], 'name': original_row['name']}
                                    changed_fields = {}
                                    if original_row['stock'] != edited_row['stock']:
                                        changed_fields['stock'] = (original_row['stock'], edited_row['stock'])
                                    if original_row['shipping_unit_price'] != edited_row['shipping_unit_price']:
                                        changed_fields['shipping_unit_price'] = (original_row['shipping_unit_price'], edited_row['shipping_unit_price'])
                                    
                                    if changed_fields:
                                        change_item['changes'] = changed_fields
                                        # [NEW] 화면 표시용 데이터 추가
                                        change_item['row_data'] = {
                                            '제품명': edited_row['name'],
                                            '구분/발주처': edited_row['customer'],
                                            '재고수량': edited_row['stock'],
                                            '단가': edited_row['shipping_unit_price']
                                        }
                                        change_list.append(change_item)
                                
                                st.session_state[changes_key] = change_list
                                st.rerun()
                    else:
                        # 기존 조회/선택 모드
                        detail_map_view = {
                            "customer": "구분/발주처", "name": "제품명", 
                            "product_type": "제품종류", "yarn_type": "사종", "weight": "중량", 
                            "size": "사이즈", "color": "색상", "shipping_unit_price": "단가", 
                            "stock": "재고수량", "order_no": "발주번호", "date": "등록/접수일", "note": "비고"
                        }
                        detail_cols_view = ["customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                        
                        for c in detail_cols_view:
                            if c not in detail_df.columns: detail_df[c] = ""
                        
                        if allow_shipping:
                            st.info("🔽 출고할 항목을 선택(체크)하면 하단에 출고 입력 폼이 나타납니다.")
                            sel_mode = "multi-row"
                        elif is_admin:
                            st.write("🔽 삭제할 항목을 선택(체크)하세요. (관리자 기능)")
                            sel_mode = "multi-row"
                        else:
                            sel_mode = "single-row"
                        
                        detail_height = min((len(detail_df) + 1) * 35 + 3, 600)
                        
                        # [NEW] 데이터 에디터 기반 선택 로직 (출고 모드일 때만)
                        if allow_shipping:
                            if f"inv_sel_state_{sel_p_code}_{key_prefix}" not in st.session_state:
                                st.session_state[f"inv_sel_state_{sel_p_code}_{key_prefix}"] = {}
                            
                            if f"inv_editor_key_{sel_p_code}_{key_prefix}" not in st.session_state:
                                st.session_state[f"inv_editor_key_{sel_p_code}_{key_prefix}"] = 0

                            df_view = detail_df[detail_cols_view].rename(columns=detail_map_view)
                            df_view.insert(0, "선택", detail_df['id'].map(st.session_state[f"inv_sel_state_{sel_p_code}_{key_prefix}"]).fillna(False))

                            edited_detail = st.data_editor(
                                df_view,
                                width="stretch", hide_index=True,
                                column_config={"선택": st.column_config.CheckboxColumn("선택", width="small")},
                                disabled=[c for c in df_view.columns if c != "선택"],
                                height=detail_height,
                                key=f"inv_detail_editor_{sel_p_code}_{key_prefix}_{st.session_state[f'inv_editor_key_{sel_p_code}_{key_prefix}']}"
                            )
                            
                            # 선택 상태 동기화
                            for idx, row in edited_detail.iterrows():
                                row_id = detail_df.iloc[idx]['id']
                                st.session_state[f"inv_sel_state_{sel_p_code}_{key_prefix}"][row_id] = row["선택"]
                                
                            selected_indices = edited_detail[edited_detail["선택"]].index
                        else:
                            # 기존 방식 (관리자 삭제 등)
                            selection_detail = st.dataframe(
                                detail_df[detail_cols_view].rename(columns=detail_map_view),
                                width="stretch", hide_index=True, on_select="rerun",
                                selection_mode=sel_mode, height=detail_height,
                                key=f"inv_detail_list_{sel_p_code}_{allow_shipping}_{key_prefix}"
                            )
                            selected_indices = selection_detail.selection.rows if selection_detail else []
                        
                        st.markdown(f"<div style='text-align:right; font-weight:bold; padding:5px; color:#333;'>합계 수량: {detail_df['stock'].sum():,}</div>", unsafe_allow_html=True)

                        if allow_shipping and not selected_indices.empty:
                            selected_rows_for_shipping = detail_df.iloc[selected_indices]
                        
                        if is_admin and not allow_shipping and selected_indices:
                            del_rows = detail_df.iloc[selection_detail.selection.rows]
                            st.markdown(f"#### 🗑️ 선택 항목 삭제 ({len(del_rows)}건)")
                            
                            if st.button("선택 항목 삭제", type="primary", key=f"btn_del_inv_sub_{sel_p_code}_{key_prefix}"):
                                st.session_state[f"confirm_del_{sel_p_code}_{key_prefix}"] = True
                            
                            if st.session_state.get(f"confirm_del_{sel_p_code}_{key_prefix}"):
                                st.warning("⚠️ 정말로 삭제하시겠습니까? (복구할 수 없습니다)")
                                if st.button("✅ 예, 삭제합니다", key=f"btn_yes_del_{sel_p_code}_{key_prefix}"):
                                    for idx, row in del_rows.iterrows():
                                        db.collection("orders").document(row['id']).delete()
                                    st.success("삭제되었습니다.")
                                    st.session_state[f"confirm_del_{sel_p_code}_{key_prefix}"] = False
                                    st.rerun()
                                if st.button("❌ 취소", key=f"btn_no_del_{sel_p_code}_{key_prefix}"):
                                    st.session_state[f"confirm_del_{sel_p_code}_{key_prefix}"] = False
                                    st.rerun()
                        
                        if is_admin and not allow_shipping:
                            st.divider()
                            if st.button(f"🗑️ '{sel_p_code}' 제품 재고 전체 삭제", type="secondary", key=f"btn_del_all_{sel_p_code}_{key_prefix}"):
                                st.session_state[f"confirm_del_all_{sel_p_code}_{key_prefix}"] = True
                            
                            if st.session_state.get(f"confirm_del_all_{sel_p_code}_{key_prefix}"):
                                st.warning(f"⚠️ 경고: '{sel_p_code}' 제품의 모든 재고({len(detail_df)}건)가 삭제됩니다. 이 작업은 되돌릴 수 없습니다.")
                                if st.button("✅ 예, 모두 삭제합니다", key=f"btn_yes_del_all_{sel_p_code}_{key_prefix}"):
                                    for idx, row in detail_df.iterrows():
                                        db.collection("orders").document(row['id']).delete()
                                    st.success("모든 재고가 삭제되었습니다.")
                                    st.session_state[f"confirm_del_all_{sel_p_code}_{key_prefix}"] = False
                                    st.rerun()

        # 탭 2 내용
        with tab2:
            # [수정] 상단 컨트롤 영역 레이아웃 변경 (문구를 좌측 끝으로 이동)
            c_h1, c_h2 = st.columns([7.5, 2.5])
            with c_h1:
                st.write("🔽 전체 재고 내역입니다.")
            with c_h2:
                stock_filter_opt_2 = st.radio("조회 옵션", ["전체코드보기", "재고있는 품목보기"], index=0, horizontal=True, label_visibility="collapsed", key=f"inv_stock_filter_2_{allow_shipping}_{key_prefix}")
            
            # [FIX] 변수 초기화 (Pylance 경고 해결)
            edit_mode_t2 = False
            if can_edit:
                c_toggle, _ = st.columns([2, 8])
                edit_mode_t2 = c_toggle.toggle("재고 수정 모드", key=f"edit_mode_t2_{allow_shipping}_{key_prefix}", help="활성화하면 목록에서 수량과 단가를 직접 수정할 수 있습니다.")

            full_df = df.copy()
            if 'date' in full_df.columns:
                full_df['date'] = full_df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else str(x)[:10])
            
            # [NEW] 임의 등록 재고 발주번호 마스킹
            if 'order_no' in full_df.columns:
                full_df['order_no'] = full_df['order_no'].apply(lambda x: '-' if str(x).startswith('STOCK-') else x)

            # [NEW] 재고 필터 적용 (탭별 독립 적용)
            if stock_filter_opt_2 == "재고있는 품목보기":
                full_df = full_df[full_df['stock'] > 0]

            if edit_mode_t2:
                st.info("수정할 셀을 더블클릭하여 값을 변경한 후, 하단의 '변경사항 저장' 버튼을 누르세요.")
                
                full_cols_for_editor = ["id", "product_code", "customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                for c in full_cols_for_editor:
                    if c not in full_df.columns: full_df[c] = ""

                edited_df = st.data_editor(
                    full_df,
                    column_config={
                        "id": None, "product_code": st.column_config.TextColumn("제품코드", disabled=True),
                        "customer": st.column_config.TextColumn("구분/발주처", disabled=True),
                        "name": st.column_config.TextColumn("제품명", disabled=True),
                        "product_type": st.column_config.TextColumn("제품종류", disabled=True),
                        "yarn_type": st.column_config.TextColumn("사종", disabled=True),
                        "weight": st.column_config.TextColumn("중량", disabled=True),
                        "size": st.column_config.TextColumn("사이즈", disabled=True),
                        "color": st.column_config.TextColumn("색상", disabled=True),
                        "shipping_unit_price": st.column_config.NumberColumn("단가", format="%d"),
                        "stock": st.column_config.NumberColumn("재고수량", format="%d"),
                        "order_no": st.column_config.TextColumn("발주번호", disabled=True),
                        "date": st.column_config.TextColumn("등록/접수일", disabled=True),
                        "note": st.column_config.TextColumn("비고", disabled=True),
                    },
                    column_order=full_cols_for_editor,
                    hide_index=True, height=min((len(full_df) + 1) * 35 + 3, 700),
                    key=f"inv_editor_full_{allow_shipping}_{key_prefix}"
                )

                original_df_subset = full_df.reset_index(drop=True)
                edited_df_reset = edited_df.reset_index(drop=True)
                changed_mask = (original_df_subset.ne(edited_df_reset)).any(axis=1)

                if changed_mask.any():
                    if st.button("변경사항 저장", key=f"save_changes_full_{allow_shipping}_{key_prefix}", type="primary"):
                        changed_rows = edited_df_reset[changed_mask]
                        original_changed_rows = original_df_subset[changed_mask]
                        
                        change_list = []
                        for i in changed_rows.index:
                            original_row = original_changed_rows.loc[i]
                            edited_row = changed_rows.loc[i]
                            
                            change_item = {'id': original_row['id'], 'name': original_row['name']}
                            changed_fields = {}
                            if original_row['stock'] != edited_row['stock']:
                                changed_fields['stock'] = (original_row['stock'], edited_row['stock'])
                            if original_row['shipping_unit_price'] != edited_row['shipping_unit_price']:
                                changed_fields['shipping_unit_price'] = (original_row['shipping_unit_price'], edited_row['shipping_unit_price'])
                            
                            if changed_fields:
                                change_item['changes'] = changed_fields
                                # [NEW] 화면 표시용 데이터 추가
                                change_item['row_data'] = {
                                    '제품명': edited_row['name'],
                                    '구분/발주처': edited_row['customer'],
                                    '재고수량': edited_row['stock'],
                                    '단가': edited_row['shipping_unit_price']
                                }
                                change_list.append(change_item)
                        
                        st.session_state[changes_key] = change_list
                        st.rerun()
            else:
                # 기존 조회/선택 모드
                full_map = {
                    "product_code": "제품코드", "customer": "구분/발주처", "name": "제품명", 
                    "product_type": "제품종류", "yarn_type": "사종", "weight": "중량", 
                    "size": "사이즈", "color": "색상", "shipping_unit_price": "단가", 
                    "stock": "재고수량", "order_no": "발주번호", "date": "등록/접수일", "note": "비고"
                }
                full_cols = ["product_code", "customer", "name", "product_type", "yarn_type", "weight", "size", "color", "shipping_unit_price", "stock", "order_no", "date", "note"]
                
                for c in full_cols:
                    if c not in full_df.columns: full_df[c] = ""

                if allow_shipping:
                    st.info("🔽 출고할 항목을 선택(체크)하면 하단에 출고 입력 폼이 나타납니다.")
                    sel_mode = "multi-row"
                elif is_admin:
                    st.write("🔽 삭제할 항목을 선택(체크)하세요. (관리자 기능)")
                    sel_mode = "multi-row"
                else:
                    sel_mode = "single-row"

                full_height = min((len(full_df) + 1) * 35 + 3, 700)

                # [수정] 파트너인 경우 선택 기능 비활성화 (단순 조회)
                if is_partner:
                    st.dataframe(
                        full_df[full_cols].rename(columns=full_map),
                        width="stretch", hide_index=True, height=full_height,
                        key=f"inv_full_list_{allow_shipping}_{key_prefix}"
                    )
                    selection_full = None
                else:
                    selection_full = st.dataframe(
                        full_df[full_cols].rename(columns=full_map),
                        width="stretch", hide_index=True, on_select="rerun",
                        selection_mode=sel_mode, height=full_height,
                        key=f"inv_full_list_{allow_shipping}_{key_prefix}"
                    )
                
                st.markdown(f"<div style='text-align:right; font-weight:bold; padding:5px; color:#333;'>합계 수량: {full_df['stock'].sum():,}</div>", unsafe_allow_html=True)

                if allow_shipping and selection_full and selection_full.selection.rows:
                    selected_rows_for_shipping = full_df.iloc[selection_full.selection.rows]

                if is_admin and not allow_shipping and selection_full and selection_full.selection.rows:
                    del_rows = full_df.iloc[selection_full.selection.rows]
                    st.markdown(f"#### 🗑️ 재고 삭제 (선택: {len(del_rows)}건)")
                    
                    if st.button("선택 항목 삭제", type="primary", key=f"btn_del_inv_full_{key_prefix}"):
                        st.session_state[f"confirm_del_full_{key_prefix}"] = True
                    
                    if st.session_state.get(f"confirm_del_full_{key_prefix}"):
                        st.warning("⚠️ 정말로 삭제하시겠습니까? (복구할 수 없습니다)")
                        c_conf1, c_conf2 = st.columns(2)
                        if c_conf1.button("✅ 예, 삭제합니다", key=f"btn_yes_del_full_{key_prefix}"):
                            for idx, row in del_rows.iterrows():
                                db.collection("orders").document(row['id']).delete()
                            st.success("삭제되었습니다.")
                            st.session_state[f"confirm_del_full_{key_prefix}"] = False
                            st.rerun()
                        if c_conf2.button("❌ 취소", key=f"btn_no_del_full_{key_prefix}"):
                            st.session_state[f"confirm_del_full_{key_prefix}"] = False
                            st.rerun()

        # [MOVED] 인쇄 및 엑셀 내보내기 설정 (테이블 하단으로 이동)
        st.divider()
        
        # 1. 인쇄 옵션 설정 (Expander)
        with st.expander("인쇄 옵션 설정"):
            pe_c1, pe_c2, pe_c3 = st.columns(3)
            # [수정] 옵션명에 공백 추가하여 일관성 유지
            print_mode = pe_c1.radio("출력 모드", ["요약 목록", "제품별 상세내역(그룹)", "전체 상세내역 (리스트)"], key=f"inv_p_mode_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_title = pe_c2.text_input("문서 제목", key=f"inv_p_title_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            
            pe_c4, pe_c5, pe_c6 = st.columns(3)
            p_title_size = pe_c4.number_input("제목 크기(px)", step=1, key=f"inv_p_ts_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_font_size = pe_c5.number_input("본문 글자 크기(px)", step=1, key=f"inv_p_fs_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_padding = pe_c6.number_input("셀 여백(px)", step=1, key=f"inv_p_pad_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            
            pe_c7, pe_c8 = st.columns(2)
            p_show_date = pe_c7.checkbox("출력일시 표시", key=f"inv_p_date_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_show_total = pe_c8.checkbox("하단 합계수량 표시", key=f"inv_p_total_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            
            st.caption("페이지 여백 (mm)")
            pe_m1, pe_m2, pe_m3, pe_m4 = st.columns(4)
            p_m_top = pe_m1.number_input("상단", step=1, key=f"inv_p_mt_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_m_bottom = pe_m2.number_input("하단", step=1, key=f"inv_p_mb_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_m_left = pe_m3.number_input("좌측", step=1, key=f"inv_p_ml_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_m_right = pe_m4.number_input("우측", step=1, key=f"inv_p_mr_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            
            pe_m5, pe_m6 = st.columns(2)
            p_bo = pe_m5.number_input("외곽선 굵기", step=0.1, format="%.1f", key=f"inv_p_bo_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)
            p_bi = pe_m6.number_input("안쪽선 굵기", step=0.1, format="%.1f", key=f"inv_p_bi_{allow_shipping}_{key_prefix}", on_change=save_inv_opts)

        # 엑셀 다운로드 및 인쇄 버튼 (Expander 밖으로 이동)
        c_btn_xls, c_btn_gap, c_btn_prt = st.columns([1.5, 5, 1.5])
        
        with c_btn_xls:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                if print_mode == "요약 목록":
                    summary[disp_cols].rename(columns=summary_cols).to_excel(writer, index=False, sheet_name="재고요약")
                else:
                    # 상세 내역은 리스트 형태로 저장
                    df_detail_final.to_excel(writer, index=False, sheet_name="상세재고")
            
            st.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name=f"재고현황_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        # 인쇄 버튼
        with c_btn_prt:
            if st.button("🖨️ 인쇄하기", key=f"inv_print_btn_{allow_shipping}_{key_prefix}", use_container_width=True):
                options = {
                    'ts': p_title_size, 'bs': p_font_size, 'pad': p_padding,
                    'dd': "block" if p_show_date else "none",
                    'mt': p_m_top, 'mb': p_m_bottom, 'ml': p_m_left, 'mr': p_m_right,
                    'bo': p_bo, 'bi': p_bi
                }
                
                # 합계 텍스트 생성
                def get_summary_text(count_text, total_qty):
                    if p_show_total:
                        return f"{count_text} / 총 재고수량: {total_qty:,}"
                    return count_text

                if print_mode == "요약 목록":
                    df_print = summary[disp_cols].rename(columns=summary_cols)
                    # [NEW] 천단위 구분기호 적용
                    for col in ['평균단가', '재고수량', '총재고금액']:
                        if col in df_print.columns:
                            df_print[col] = df_print[col].apply(lambda x: f"{int(x):,}" if pd.notnull(x) else "")
                    
                    total_q = summary['stock'].sum()
                    html = generate_inventory_report_html(p_title, df_print, get_summary_text(f"총 {len(df_print)}개 품목", total_q), options, right_align_cols=['평균단가', '재고수량', '총재고금액'])
                    st.components.v1.html(html, height=0, width=0)
                    
                elif print_mode == "전체 상세내역 (리스트)":
                    # 제품코드, 제품명 순으로 정렬
                    if "제품코드" in df_detail_final.columns:
                        df_detail_final = df_detail_final.sort_values(by=["제품코드", "제품명"])
                    
                    # [NEW] 천단위 구분기호 적용
                    for col in ['단가', '재고수량', '중량']:
                        if col in df_detail_final.columns:
                            df_detail_final[col] = df_detail_final[col].apply(lambda x: f"{int(x):,}" if pd.notnull(x) and str(x).replace('.','',1).isdigit() else x)

                    # [FIX] 컬럼명 변경 반영 (stock -> 재고수량)
                    # df_detail_final의 재고수량은 이미 문자열로 변환되었으므로 원본 df에서 합계 계산
                    total_q = df['stock'].sum()
                    html = generate_inventory_report_html(p_title, df_detail_final, get_summary_text(f"총 {len(df_detail_final)}건", total_q), options, right_align_cols=['단가', '재고수량', '중량'])
                    st.components.v1.html(html, height=0, width=0)
                    
                elif print_mode == "제품별 상세내역(그룹)":
                    # 커스텀 HTML 생성 (제품별 그룹핑)
                    print_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    date_display = "block" if p_show_date else "none"
                    
                    html_content = f"""
                    <html>
                    <head>
                        <title>{p_title}</title>
                        <style>
                            @page {{ margin: {p_m_top}mm {p_m_right}mm {p_m_bottom}mm {p_m_left}mm; }}
                            body {{ font-family: 'Malgun Gothic', sans-serif; padding: 0; margin: 0; }}
                            h2 {{ text-align: center; margin-bottom: 5px; font-size: {p_title_size}px; }}
                            .info {{ text-align: right; font-size: 12px; margin-bottom: 10px; color: #555; display: {date_display}; }}
                            table {{ width: 100%; border-collapse: collapse; font-size: {p_font_size}px; margin-bottom: 20px; border: {p_bo}px solid #444; }}
                            th, td {{ border: {p_bi}px solid #444; padding: {p_padding}px; text-align: center; }}
                            th {{ background-color: #f0f0f0; }}
                            /* [NEW] 우측 정렬 클래스 */
                            .align-right {{ text-align: right; }}
                            .group-header {{ background-color: #e6f3ff; font-weight: bold; text-align: left; padding: 8px; border: 1px solid #444; margin-top: 10px; }}
                            .no-data {{ text-align: center; padding: 10px; color: #888; }}
                            .grand-total {{ text-align: right; font-weight: bold; font-size: {p_font_size + 2}px; margin-top: 20px; border-top: 2px solid #333; padding-top: 10px; }}
                            @media screen {{ body {{ display: none; }} }}
                        </style>
                    </head>
                    <body onload="window.print()">
                        <h2>{p_title}</h2>
                        <div class="info">출력일시: {print_now}</div>
                    """
                    
                    grand_total_stock = 0
                    # 요약 목록 순서대로 반복
                    for _, row in summary.iterrows():
                        p_code = row['product_code']
                        p_name = row.get('name', '')
                        p_type = row.get('product_type', '')
                        p_stock = int(row.get('stock', 0))
                        
                        # 해당 제품의 상세 내역 필터링
                        sub_df = df_detail_final[df_detail_final['제품코드'] == p_code]
                        grand_total_stock += p_stock

                        # [NEW] 천단위 구분기호 적용 (출력용 복사본)
                        sub_df_print = sub_df.copy()
                        for col in ['단가', '재고수량', '중량']:
                            if col in sub_df_print.columns:
                                sub_df_print[col] = sub_df_print[col].apply(lambda x: f"{int(x):,}" if pd.notnull(x) and str(x).replace('.','',1).isdigit() else x)
                        
                        # 그룹 헤더
                        html_content += f"""
                        <div class="group-header">
                            📦 [{p_code}] {p_type} / {p_name} (총 재고: {p_stock:,})
                        </div>
                        """
                        
                        if not sub_df_print.empty:
                            # 상세 테이블
                            # [NEW] to_html 대신 직접 생성하거나 to_html 후 클래스 주입
                            # 여기서는 to_html 사용 후 CSS로 제어하기 어려우므로, 특정 컬럼에 클래스를 줄 수 없으니
                            # generate_inventory_report_html 로직을 응용하거나, to_html의 formatters 사용
                            # 하지만 formatters는 값만 바꿈. 정렬은 CSS.
                            # 간단하게 to_html 결과에 style 주입은 어려우므로, 위에서 정의한 CSS nth-child 활용을 위해
                            # 테이블에 클래스를 주거나, 인라인 스타일을 가진 HTML을 생성해야 함.
                            # 여기서는 간단히 sub_df_print를 HTML로 변환하고, 위쪽 CSS에서 nth-child로 제어하도록 함.
                            # 단, 컬럼 순서가 고정되어야 함.
                            
                            # 컬럼 순서 고정 (화면에 보이는 순서대로)
                            # detail_cols_view와 유사하게
                            cols_to_show = [c for c in sub_df_print.columns if c not in ['제품코드', '제품명', '제품종류', '사종', '중량', '사이즈']] # 공통 정보 제외하고 보여줄 수도 있지만, 여기서는 전체 보여줌
                            
                            # [FIX] 우측 정렬을 위해 CSS nth-child 사용 (단가, 재고수량 등 위치 확인 필요)
                            # 여기서는 간단히 전체 테이블 렌더링
                            html_content += sub_df_print.to_html(index=False, border=1, classes='detail-table')
                        else:
                            html_content += "<div class='no-data'>상세 내역 없음</div>"
                            
                    if p_show_total:
                        html_content += f"<div class='grand-total'>총 재고수량 합계: {grand_total_stock:,}</div>"

                    html_content += "</body></html>"
                    st.components.v1.html(html_content, height=0, width=0)

        # [MOVED] 출고 처리 로직 (공통)
        if allow_shipping and selected_rows_for_shipping is not None and not selected_rows_for_shipping.empty:
            sel_rows = selected_rows_for_shipping
            
            st.divider()
            st.markdown(f"#### 선택 항목 출고 ({len(sel_rows)}건)")
            
            st.markdown("##### 1. 출고 품목 상세 입력")
            
            staging_data = []
            for idx, row in sel_rows.iterrows():
                with st.container(border=True):
                    # [NEW] 1. 제품 정보 한 줄 표시
                    stock = int(row.get('stock', 0))
                    price = int(row.get('shipping_unit_price', 0))
                    
                    info_line = f"**{row.get('name')}** ({row.get('color', '')}/{row.get('size', '')}) | 중량: {row.get('weight', 0)}g | **현재고: {stock:,}** | 기본단가: {price:,}원"
                    st.markdown(info_line, unsafe_allow_html=True)

                    # [NEW] 2. 입력 필드 (하단 정렬, 기본값 0)
                    c_qty, c_price, c_note = st.columns([2, 1.5, 3], vertical_alignment="bottom")
                    
                    with c_qty:
                        qty_key = f"inv_ship_qty_{row['id']}_{key_prefix}"
                        chk_key = f"inv_ship_all_chk_{row['id']}_{key_prefix}"

                        # [수정] 라벨과 체크박스를 한 줄에 배치 (높이 정렬)
                        qc1, qc2 = st.columns([0.6, 0.4], vertical_alignment="center")
                        qc1.markdown("**출고수량**")
                        is_ship_all = qc2.checkbox("[전량]", key=chk_key)
                        
                        # [FIX] 체크박스가 켜져있으면 세션 상태 강제 업데이트
                        if is_ship_all:
                            st.session_state[qty_key] = stock
                        
                        # 세션값 가져오기 (없으면 0)
                        current_qty = st.session_state.get(qty_key, 0)
                        
                        qty = st.number_input("출고수량", min_value=0, max_value=stock, value=current_qty, step=10, key=qty_key, label_visibility="collapsed")

                    with c_price:
                        # [수정] 라벨 높이 맞춤
                        pc1, pc2 = st.columns([1, 0.1])
                        pc1.markdown("**단가(원)**")
                        price_input = st.number_input("단가", min_value=0, value=price, step=100, key=f"inv_ship_price_{row['id']}_{key_prefix}", label_visibility="collapsed")
                    
                    with c_note:
                        # [수정] 라벨 높이 맞춤
                        nc1, nc2 = st.columns([1, 0.1])
                        nc1.markdown("**비고**")
                        note_input = st.text_input("비고", value=row.get('note', ''), placeholder="비고 사항 입력", key=f"inv_ship_note_{row['id']}_{key_prefix}", label_visibility="collapsed")

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
            
            # 유효성 검사
            is_valid_qty = True
            if not valid_staging.empty:
                for _, row in valid_staging.iterrows():
                    if row['출고수량'] > row['현재고']:
                        st.error(f"출고수량 확인(재고부족): {row['제품명']}")
                        is_valid_qty = False
            
            total_ship_qty = valid_staging['출고수량'].sum() if not valid_staging.empty else 0
            total_est_amt = (valid_staging['출고수량'] * valid_staging['단가']).sum() if not valid_staging.empty else 0
            
            # UI 그룹화를 위해 st.container 사용
            with st.container():
                # [수정] 상세 배송 정보 입력 폼으로 확장 (주문별 출고와 동일하게)
                st.markdown("##### 2. 배송 및 운임 정보")
                c1, c2, c3 = st.columns(3)
                q_date = c1.date_input("출고일자", datetime.date.today())
                shipping_methods = get_common_codes("shipping_methods", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"])
                q_method = c2.selectbox("배송방법", shipping_methods)
                
                shipping_partners = get_partners("배송업체")
                q_carrier = c3.selectbox("배송업체", ["직접입력"] + shipping_partners)
                if q_carrier == "직접입력":
                    final_carrier = c3.text_input("업체명 직접입력", placeholder="")
                else:
                    final_carrier = q_carrier

                st.markdown("##### 납품처 정보")
                first_row = sel_rows.iloc[0]
                
                # [NEW] 선택 변경 감지 및 주소 필드 초기화 (재고 출고용)
                if f"last_inv_ship_sel_id_{key_prefix}" not in st.session_state:
                    st.session_state[f"last_inv_ship_sel_id_{key_prefix}"] = None
                
                # 첫 번째 행의 ID가 바뀌면 선택이 바뀐 것으로 간주
                if st.session_state[f"last_inv_ship_sel_id_{key_prefix}"] != first_row['id']:
                    # [FIX] NaN 값 처리
                    addr_val = first_row.get('delivery_address')
                    st.session_state[f"inv_ship_addr_input_{key_prefix}"] = str(addr_val) if addr_val and not pd.isna(addr_val) else ""
                    st.session_state[f"inv_ship_addr_detail_input_{key_prefix}"] = ""
                    st.session_state[f"last_inv_ship_sel_id_{key_prefix}"] = first_row['id']
                    # [FIX] 선택 변경 시 팝업 강제 닫기
                    st.session_state[f"show_inv_ship_addr_dialog_{key_prefix}"] = False

                # 재고 데이터에는 배송지 정보가 없을 수 있으므로 빈 값 또는 기본값 처리
                c_d1, c_d2 = st.columns(2)
                # [FIX] NaN 값 처리
                val_to = first_row.get('delivery_to', first_row.get('customer', ''))
                val_contact = first_row.get('delivery_contact', '')
                q_to = c_d1.text_input("납품처명", value=str(val_to) if pd.notna(val_to) else '')
                q_contact = c_d2.text_input("납품연락처", value=str(val_contact) if pd.notna(val_contact) else '')

                # [FIX] 주소 입력 필드 레이아웃 정의
                c_addr1, c_addr2, c_addr3 = st.columns([3.5, 2, 0.5], vertical_alignment="bottom")
                q_addr = c_addr1.text_input("납품주소", key=f"inv_ship_addr_input_{key_prefix}")
                q_addr_detail = c_addr2.text_input("상세주소", key=f"inv_ship_addr_detail_input_{key_prefix}")
                # [FIX] 버튼 키를 동적으로 생성하여 선택 변경 시 상태 간섭 원천 차단
                if c_addr3.button("🔍 주소", key=f"btn_search_inv_ship_addr_{allow_shipping}_{first_row['id']}_{key_prefix}", use_container_width=True):
                    st.session_state[f"show_inv_ship_addr_dialog_{key_prefix}"] = True
                q_note = st.text_area("비고 (송장번호/차량번호 등)", placeholder="예: 경동택배 123-456-7890")

                # [FIX] 부가세 포함 기본 체크
                q_vat_inc = st.checkbox("단가에 부가세 포함", value=True, key=f"inv_quick_ship_vat_{key_prefix}")
                if q_vat_inc:
                    q_supply_price = int(total_est_amt / 1.1)
                    q_vat = total_est_amt - q_supply_price
                else:
                    q_supply_price = total_est_amt
                    q_vat = int(total_est_amt * 0.1)
                    total_est_amt += q_vat
                    
                st.info(f"💰 **예상 합계**: 수량 {total_ship_qty:,}장 / 금액 {total_est_amt:,}원 (공급가 {q_supply_price:,} + 부가세 {q_vat:,})")
                
                # [NEW] 운임비 입력 (리스트 형태)
                st.markdown("##### 운임비 설정")
                
                cost_list_key = f"inv_ship_cost_list_{allow_shipping}_{key_prefix}"
                if cost_list_key not in st.session_state:
                    st.session_state[cost_list_key] = [{"내용": "택배비", "건수": 1, "단가": 0}]
                
                cost_items = st.session_state[cost_list_key]
                indices_to_remove = []
                total_shipping_cost = 0
                
                for i, item in enumerate(cost_items):
                    cc1, cc2, cc3, cc4 = st.columns([2, 1, 1.5, 0.8], vertical_alignment="bottom")
                    with cc1:
                        if i == 0: st.markdown("항목명")
                        item['내용'] = st.text_input("항목명", value=item.get('내용', ''), key=f"inv_sc_name_{i}_{allow_shipping}", label_visibility="collapsed")
                    with cc2:
                        if i == 0: st.markdown("건수")
                        item['건수'] = st.number_input("건수", min_value=1, value=item.get('건수', 1), step=1, key=f"inv_sc_count_{i}_{allow_shipping}", label_visibility="collapsed")
                    with cc3:
                        if i == 0: st.markdown("단가")
                        item['단가'] = st.number_input("단가", min_value=0, value=item.get('단가', 0), step=500, key=f"inv_sc_price_{i}_{allow_shipping}", label_visibility="collapsed")
                    with cc4:
                        if st.button("삭제", key=f"inv_sc_del_{i}_{allow_shipping}"):
                            indices_to_remove.append(i)
                    total_shipping_cost += item.get('건수', 1) * item.get('단가', 0)

                if indices_to_remove:
                    for i in sorted(indices_to_remove, reverse=True):
                        del st.session_state[cost_list_key][i]
                    st.rerun()
                    
                if st.button("➕ 운임비 항목 추가", key=f"inv_add_cost_{allow_shipping}"):
                    st.session_state[cost_list_key].append({"내용": "", "건수": 1, "단가": 0})
                    st.rerun()

                st.write(f"**🚛 운임비 합계: {total_shipping_cost:,}원**")

                q_cost_mode = st.radio("운임비 적용 방식", ["묶음 운임비(마지막행 포함)", "건당 운임비"], horizontal=True, help="묶음 운임비: 목록의 맨 마지막 항목에만 운임비 전액을 부과합니다. (거래명세서 하단 표시용)", key=f"inv_ship_cost_mode_{allow_shipping}")

                submitted = st.button("출고 처리", type="primary", disabled=not is_valid_qty, use_container_width=True, key=f"inv_ship_submit_{allow_shipping}")

            # 주소 검색 팝업 표시
            if st.session_state.show_inv_ship_addr_dialog:
                show_address_search_modal_inv_ship()

            if submitted:
                # [NEW] 운임비 상세 내역 리스트 변환 (DB 저장용)
                cost_lines = []
                for item in st.session_state.get(cost_list_key, []):
                    if item.get('단가', 0) > 0 or item.get('건수', 1) > 0:
                        cost_lines.append({ "name": item.get('내용', ''), "qty": item.get('건수', 1), "price": item.get('단가', 0) })

                total_items = len(edited_staging)
                last_idx = edited_staging.index[-1] if total_items > 0 else -1
                
                # [FIX] 배치 내 모든 항목에 동일한 시간 적용 (정렬 문제 해결)
                now_dt = datetime.datetime.now()
                shipping_dt = datetime.datetime.combine(q_date, now_dt.time())

                shipped_rows = [] # [NEW] 명세서 발행용 데이터 수집

                for idx, row in edited_staging.iterrows():
                    doc_id = row['id']
                    ship_qty = int(row['출고수량'])
                    q_price = int(row['단가'])
                    q_note_item = str(row['비고'])
                    
                    cost_per_item = 0
                    current_cost_lines = [] # 현재 행에 저장할 운임비 상세

                    if total_shipping_cost > 0:
                        if q_cost_mode == "건당 운임비":
                            cost_per_item = total_shipping_cost
                            current_cost_lines = cost_lines
                        else:
                            if idx == last_idx:
                                cost_per_item = total_shipping_cost
                                current_cost_lines = cost_lines
                            else:
                                cost_per_item = 0
                                current_cost_lines = []
                    
                    update_data = {
                        "status": "출고완료",
                        "shipping_date": shipping_dt, # [FIX] 고정된 시간 사용
                        "shipping_method": q_method,
                        "shipping_carrier": final_carrier,
                        "shipping_cost": cost_per_item,
                        "shipping_cost_lines": current_cost_lines, # [NEW] 상세 내역 저장
                        "shipping_unit_price": q_price,
                        "vat_included": q_vat_inc,
                        "delivery_to": q_to, "delivery_contact": q_contact, "delivery_address": f"{q_addr} {q_addr_detail}".strip(),
                        "note": q_note_item if q_note_item else q_note
                    }
                    
                    # 부분 출고 로직
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
                        db.collection("orders").document(row['id']).update(update_data)
                        
                        # 명세서용 데이터 추가 (원본 데이터 + 업데이트 데이터)
                        # sel_rows에서 원본 데이터 찾기
                        original_row = sel_rows[sel_rows['id'] == doc_id].iloc[0].to_dict()
                        original_row.update(update_data)
                        original_row['stock'] = ship_qty
                        shipped_rows.append(original_row)

                st.success(f"{len(valid_staging)}건 출고 처리 완료!")
                
                # [FIX] 완료 후 선택 상태 초기화 (모든 제품 코드에 대해)
                # 현재 선택된 행들의 제품 코드를 수집하여 초기화
                for p_code in sel_rows['product_code'].unique():
                    st.session_state[f"inv_sel_state_{p_code}_{key_prefix}"] = {}
                    ek = f"inv_editor_key_{p_code}_{key_prefix}"
                    if ek not in st.session_state: st.session_state[ek] = 0
                    st.session_state[ek] += 1

                # [NEW] 출고된 데이터를 세션에 저장 (거래명세서 확인 버튼 활성화용)
                st.session_state["last_shipped_data"] = pd.DataFrame(shipped_rows)
                st.rerun()
        elif allow_shipping:
            st.info("👆 목록에서 출고할 항목을 선택해주세요.")

def render_inventory(db, sub_menu):
    st.header("재고 현황")
    st.info("현재 보유 중인 완제품 재고를 조회합니다.")
    
    if sub_menu == "재고 임의 등록":
        st.subheader("재고 임의 등록 (자체 생산/기존 재고)")
        st.info("발주서 없이 보유하고 있는 재고나 자체 생산분을 등록하여 출고 가능한 상태로 만듭니다.")
        
        # [NEW] 관리자 전용 엑셀 업로드 기능
        if st.session_state.get("role") == "admin":
            with st.expander("엑셀 파일로 일괄 등록 (관리자 전용)", expanded=False):
                st.markdown("""
                **업로드 규칙**
                1. 아래 **양식 다운로드** 버튼을 눌러 엑셀 파일을 받으세요.
                2. `제품코드`는 시스템에 등록된 코드와 정확히 일치해야 합니다.
                3. `수량`과 `단가`는 숫자만 입력하세요.
                """)
                
                # 양식 다운로드
                template_data = {
                    "제품코드": ["A20S0904080"],
                    "발주처": ["자체보유"],
                    "제품명": ["자체재고"],
                    "색상": ["기본"],
                    "중량": [150],
                    "사이즈": ["40*80"],
                    "수량": [100],
                    "단가": [5000],
                    "비고": ["기초재고"],
                    "등록일자": [datetime.date.today().strftime("%Y-%m-%d")]
                }
                df_template = pd.DataFrame(template_data)
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_template.to_excel(writer, index=False)
                    
                st.download_button(
                    label="📥 업로드용 양식 다운로드",
                    data=buffer.getvalue(),
                    file_name="재고등록양식.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
                uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx", "xls"], key="inv_upload")
                
                if uploaded_file:
                    try:
                        df_upload = pd.read_excel(uploaded_file)
                        st.write("데이터 미리보기:")
                        st.dataframe(df_upload.head())
                        
                        if st.button("일괄 등록 시작", type="primary", key="btn_inv_upload"):
                            # 제품 목록 미리 가져오기 (매핑용)
                            products_ref = db.collection("products").stream()
                            product_map = {p.id: p.to_dict() for p in products_ref}
                            
                            success_count = 0
                            error_logs = []
                            
                            progress_bar = st.progress(0)
                            
                            for idx, row in df_upload.iterrows():
                                p_code = str(row.get("제품코드", "")).strip()
                                if p_code not in product_map:
                                    error_logs.append(f"{idx+2}행: 제품코드 '{p_code}'가 존재하지 않습니다.")
                                    continue
                                    
                                product_info = product_map[p_code]
                                
                                # 임의의 발주번호 생성 (STOCK-YYMMDD-UUID)
                                stock_no = f"STOCK-{datetime.datetime.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
                                
                                # 날짜 처리
                                try:
                                    reg_date_val = row.get("등록일자")
                                    if pd.isna(reg_date_val):
                                        reg_date = datetime.datetime.now()
                                    else:
                                        reg_date = pd.to_datetime(reg_date_val).to_pydatetime()
                                except:
                                    reg_date = datetime.datetime.now()
                                
                                reg_name = str(row.get("제품명", "")).strip()
                                final_name = reg_name if reg_name and reg_name != "nan" else product_info.get('product_type', '자체제품')
                                
                                # [NEW] 추가 컬럼 처리 (발주처, 색상, 중량, 사이즈)
                                reg_customer = str(row.get("발주처", "")).strip()
                                if not reg_customer or reg_customer == "nan": reg_customer = "자체보유"
                                
                                reg_color = str(row.get("색상", "")).strip()
                                if not reg_color or reg_color == "nan": reg_color = "기본"
                                
                                try:
                                    reg_weight = int(row.get("중량"))
                                except:
                                    try: reg_weight = int(product_info.get('weight', 0))
                                    except: reg_weight = 0
                                
                                reg_size = str(row.get("사이즈", "")).strip()
                                if not reg_size or reg_size == "nan": reg_size = product_info.get('size', '')

                                try:
                                    stock_val = int(row.get("수량", 0))
                                    price_val = int(row.get("단가", 0))
                                except:
                                    stock_val = 0
                                    price_val = 0

                                doc_data = {
                                    "product_code": p_code,
                                    "product_type": product_info.get('product_type'),
                                    "yarn_type": product_info.get('yarn_type'),
                                    "weight": product_info.get('weight'),
                                    "size": product_info.get('size'),
                                    "weight": reg_weight,
                                    "size": reg_size,
                                    "name": final_name,
                                    "color": "기본",
                                    "color": reg_color,
                                    "order_no": stock_no,
                                    "customer": "자체보유",
                                    "customer": reg_customer,
                                    "date": reg_date,
                                    "stock": stock_val,
                                    "shipping_unit_price": price_val,
                                    "status": "봉제완료", # 즉시 출고 가능 상태
                                    "note": str(row.get("비고", "")) if pd.notna(row.get("비고")) else ""
                                }
                                
                                db.collection("orders").add(doc_data)
                                success_count += 1
                                progress_bar.progress((idx + 1) / len(df_upload))
                                
                            if success_count > 0:
                                st.success(f"✅ {success_count}건의 재고가 등록되었습니다.")
                            
                            if error_logs:
                                st.error(f"⚠️ {len(error_logs)}건의 오류가 발생했습니다.")
                                for log in error_logs:
                                    st.write(log)
                            
                            if success_count > 0:
                                st.rerun()
                                
                    except Exception as e:
                        st.error(f"파일 처리 중 오류가 발생했습니다: {e}")
            
            st.divider()

        # 제품 목록 가져오기
        products_ref = db.collection("products").stream()
        products_list = [p.to_dict() for p in products_ref]
        if not products_list:
            st.warning("등록된 제품이 없습니다. 제품 관리에서 제품을 먼저 등록해주세요.")
        else:
            # [수정] 다중 조건 필터링을 위한 기초 코드 로드
            product_types = get_common_codes("product_types", [])
            yarn_types = get_common_codes("yarn_types_coded", [])
            weight_codes = get_common_codes("weight_codes", [])
            size_codes = get_common_codes("size_codes", [])

            # 필터링 UI
            st.markdown("##### 제품 검색 조건")
            f1, f2, f3, f4 = st.columns(4)
            
            # 옵션 생성 (전체 포함)
            pt_opts = ["전체"] + [p['name'] for p in product_types]
            yt_opts = ["전체"] + [y['name'] for y in yarn_types]
            wt_opts = ["전체"] + [w['name'] for w in weight_codes]
            sz_opts = ["전체"] + [s['name'] for s in size_codes]

            sel_pt = f1.selectbox("제품종류", pt_opts, key="inv_reg_pt")
            sel_yt = f2.selectbox("사종", yt_opts, key="inv_reg_yt")
            sel_wt = f3.selectbox("중량", wt_opts, key="inv_reg_wt")
            sel_sz = f4.selectbox("사이즈", sz_opts, key="inv_reg_sz")

            # 제품 목록 필터링
            filtered_products = products_list
            if sel_pt != "전체": filtered_products = [p for p in filtered_products if p.get('product_type') == sel_pt]
            if sel_yt != "전체": filtered_products = [p for p in filtered_products if p.get('yarn_type') == sel_yt]
            if sel_wt != "전체":
                # 선택된 중량 명칭에 해당하는 코드값(숫자)을 찾아서 비교
                target_w_code = next((w['code'] for w in weight_codes if w['name'] == sel_wt), None)
                if target_w_code:
                    filtered_products = [p for p in filtered_products if str(p.get('weight')) == str(target_w_code)]
            if sel_sz != "전체": filtered_products = [p for p in filtered_products if p.get('size') == sel_sz]

            if not filtered_products:
                st.warning("조건에 맞는 제품이 없습니다.")
            else:
                # 필터링된 제품 선택
                # [수정] 표시 형식 변경: 코드 : 종류 / 사종 / 중량 / 사이즈
                p_options = [f"{p['product_code']} : {p.get('product_type', '')} / {p.get('yarn_type', '')} / {p.get('weight', '')}g / {p.get('size', '')}" for p in filtered_products]
                
                # [수정] 제품 선택을 폼 밖으로 이동하여 상세 정보 기본값 로드
                sel_p_str = st.selectbox("제품 선택", p_options)
                sel_code = sel_p_str.split(" : ")[0]
                sel_product = next((p for p in filtered_products if p['product_code'] == sel_code), None)
                
                # 기본값 설정
                def_name = sel_product.get('product_type', '자체제품') if sel_product else ""
                def_weight = int(sel_product.get('weight', 0)) if sel_product else 0
                def_size = sel_product.get('size', '') if sel_product else ""
                
                partners = get_partners("발주처")
                
                # 폼 리셋을 위한 키
                if "stock_reg_key" not in st.session_state:
                    st.session_state["stock_reg_key"] = 0
                rk = st.session_state["stock_reg_key"]

                with st.form("stock_reg_form"):
                    st.write("상세 정보 입력")
                    
                    # Row 1: 등록일자, 발주처
                    c1, c2 = st.columns(2)
                    reg_date = c1.date_input("등록일자", datetime.date.today(), key=f"reg_date_{sel_code}_{rk}")
                    if partners:
                        reg_customer = c2.selectbox("발주처 (구분)", partners, help="거래처관리에서 등록한 '자체발주' 등을 선택하세요.", key=f"reg_cust_{sel_code}_{rk}")
                    else:
                        reg_customer = c2.text_input("발주처 (구분)", key=f"reg_cust_txt_{sel_code}_{rk}")
                    
                    # Row 2: 제품명, 색상, 수량
                    c3, c4, c5 = st.columns(3)
                    reg_name = c3.text_input("제품명", value=def_name, key=f"reg_name_{sel_code}_{rk}")
                    reg_color = c4.text_input("색상", value="기본", key=f"reg_color_{sel_code}_{rk}")
                    reg_qty = c5.number_input("재고 수량(장)", min_value=1, step=10, key=f"reg_qty_{sel_code}_{rk}")
                    
                    # Row 3: 중량, 사이즈 (추가 요청)
                    c6, c7 = st.columns(2)
                    reg_weight = c6.number_input("중량(g)", value=def_weight, step=10, key=f"reg_weight_{sel_code}_{rk}")
                    reg_size = c7.text_input("사이즈", value=def_size, key=f"reg_size_{sel_code}_{rk}")

                    # Row 4: 단가, 비고
                    c8, c9 = st.columns(2)
                    reg_price = c8.number_input("단가 (원)", min_value=0, step=100, help="재고 평가 단가", key=f"reg_price_{sel_code}_{rk}")
                    reg_note = c9.text_input("비고", value="자체재고", key=f"reg_note_{sel_code}_{rk}")

                    if st.form_submit_button("재고 등록"):
                        if sel_product:
                            # [FIX] IndentationError 수정
                            stock_no = f"STOCK-{datetime.datetime.now().strftime('%y%m%d-%H%M%S')}"
                            doc_data = {
                                "product_code": sel_code,
                                "product_type": sel_product.get('product_type'),
                                "yarn_type": sel_product.get('yarn_type'),
                                "weight": reg_weight, "size": reg_size,
                                "name": reg_name, "color": reg_color,
                                "order_no": stock_no, "customer": reg_customer,
                                "date": datetime.datetime.combine(reg_date, datetime.datetime.now().time()),
                                "stock": reg_qty, "shipping_unit_price": reg_price,
                                "status": "봉제완료", "note": reg_note
                            }
                            db.collection("orders").add(doc_data)
                            st.success(f"재고가 등록되었습니다. (번호: {stock_no})")
                            st.session_state["stock_reg_key"] += 1
                            st.rerun()

    elif sub_menu == "재고 현황 조회":
        # 재고 현황 조회 (출고 기능 없음)
        render_inventory_logic(db, allow_shipping=False, key_prefix="inv_view")