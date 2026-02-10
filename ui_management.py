import streamlit as st
import pandas as pd
import datetime
import io
from firebase_admin import firestore
from utils import get_common_codes, get_partners, is_basic_code_used, manage_code, manage_code_with_code

def render_shipping(db):
    st.header("🚚 출고 현황")
    st.info("완성된 제품을 출고 처리하거나, 출고된 내역의 거래명세서를 발행합니다.")
    
    if "shipping_key" not in st.session_state:
        st.session_state["shipping_key"] = 0

    tab1, tab2, tab3 = st.tabs(["🚀 출고 대기 관리", "📋 출고 완료 내역 (명세서)", "📊 배송/운임 통계"])
    
    shipping_partners = get_partners("배송업체")
    
    with tab1:
        st.subheader("출고 대기 목록 (봉제완료)")
        docs = db.collection("orders").where("status", "==", "봉제완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
        rows.sort(key=lambda x: x.get('date', datetime.datetime.max))
        
        if rows:
            df = pd.DataFrame(rows)
            
            # 날짜 포맷팅
            if 'date' in df.columns:
                df['date'] = df['date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)

            col_map = {
                "product_code": "제품코드", "order_no": "발주번호", "date": "접수일", 
                "customer": "발주처", "name": "제품명", "weight": "중량(g)", "stock": "수량",
                "delivery_to": "납품처", "delivery_contact": "연락처", "delivery_address": "주소", "note": "비고"
            }
            display_cols = ["product_code", "order_no", "date", "customer", "name", "weight", "stock", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 출고할 항목을 선택(체크)하세요. (다중 선택 가능)")
            selection = st.dataframe(
                df[final_cols].rename(columns=col_map),
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key=f"ship_wait_list_{st.session_state['shipping_key']}"
            )
            
            if selection.selection.rows:
                selected_indices = selection.selection.rows
                selected_rows = df.iloc[selected_indices]
                
                st.divider()
                st.markdown(f"### 🚚 배송 정보 입력 (선택된 {len(selected_rows)}건)")
                
                # 배송 정보 입력 폼
                with st.form("shipping_process_form"):
                    c1, c2, c3, c4 = st.columns(4)
                    s_date = c1.date_input("출고일자", datetime.date.today())
                    s_method = c2.selectbox("배송방법", ["택배", "화물", "용차", "직배송", "퀵서비스", "기타"])
                    s_carrier = c3.selectbox("배송업체", ["직접입력"] + shipping_partners)
                    if s_carrier == "직접입력":
                        s_carrier_input = c3.text_input("업체명 직접입력", placeholder="택배사/기사님 성함")
                        final_carrier = s_carrier_input
                    else:
                        final_carrier = s_carrier
                    
                    # [수정] 운임비 적용 방식 로직 개선 (명칭 변경 및 조건부 표시)
                    if len(selected_rows) > 1:
                        s_cost_mode = st.radio("운임비 적용 방식", ["개별 운임비", "묶음 운임비"], index=1, horizontal=True, help="개별: 각 건마다 입력한 비용 적용 / 묶음: 입력한 총 비용을 건수로 나눔")
                    else:
                        s_cost_mode = "개별 운임비"
                        st.caption("운임비 적용: **개별 운임비** (단일 건)")
                    
                    s_cost = c4.number_input("운임비 입력(원)", min_value=0, step=100)

                    st.markdown("##### 📍 납품처 정보 (일괄 적용)")
                    st.caption("여러 건을 묶음 배송(용차 등)할 때, 아래 정보를 입력하면 선택된 모든 건의 배송지가 변경됩니다.")
                    
                    # 첫 번째 선택된 행의 정보를 기본값으로 사용
                    first_row = selected_rows.iloc[0]
                    
                    c_d1, c_d2, c_d3 = st.columns(3)
                    d_to = c_d1.text_input("납품처명", value=first_row.get('delivery_to', ''))
                    d_contact = c_d2.text_input("납품연락처", value=first_row.get('delivery_contact', ''))
                    d_addr = c_d3.text_input("납품주소", value=first_row.get('delivery_address', ''))
                    
                    s_note = st.text_area("비고 (송장번호/차량번호 등)", placeholder="예: 경동택배 123-456-7890")

                    # 단일 선택 시 부분 출고 옵션 제공
                    partial_ship = False
                    ship_qty = 0
                    current_stock = 0
                    
                    if len(selected_rows) == 1:
                        current_stock = int(first_row.get('stock', 0))
                        st.markdown("##### 📦 수량 확인")
                        ship_qty = st.number_input("출고 수량", min_value=1, max_value=current_stock, value=current_stock, step=10, help="전량 출고 시 그대로 두세요.")
                        if ship_qty < current_stock:
                            partial_ship = True
                            st.info(f"ℹ️ 부분 출고: {ship_qty}장 출고 후 {current_stock - ship_qty}장은 대기 목록에 남습니다.")
                    else:
                        total_qty = selected_rows['stock'].sum()
                        st.markdown(f"##### 📦 총 출고 수량: **{total_qty:,}장** (일괄 전량 출고)")

                    if st.form_submit_button("🚀 출고 처리"):
                        # 운임비 계산
                        total_items = len(selected_rows)
                        if total_items > 0:
                            if s_cost_mode == "묶음 운임비":
                                # 총 비용을 N빵 (통계 처리를 위해 개별 항목에 분산 저장)
                                cost_per_item = int(s_cost / total_items)
                            else:
                                # 건당 비용 적용
                                cost_per_item = s_cost
                        else:
                            cost_per_item = 0
                        
                        for idx, row in selected_rows.iterrows():
                            doc_id = row['id']
                            
                            # 공통 업데이트 데이터
                            update_data = {
                                "status": "출고완료",
                                "shipping_date": datetime.datetime.combine(s_date, datetime.datetime.now().time()),
                                "shipping_method": s_method,
                                "shipping_carrier": final_carrier,
                                "shipping_cost": cost_per_item,
                                "delivery_to": d_to,
                                "delivery_contact": d_contact,
                                "delivery_address": d_addr,
                                "note": s_note # 기존 비고 덮어쓰기 (배송 정보 위주)
                            }

                            if partial_ship and len(selected_rows) == 1:
                                # 부분 출고: 새 문서 생성(출고분) + 기존 문서 업데이트(잔여분)
                                doc_ref = db.collection("orders").document(doc_id)
                                org_data = doc_ref.get().to_dict()
                                
                                new_ship_doc = org_data.copy()
                                new_ship_doc.update(update_data)
                                new_ship_doc['stock'] = ship_qty
                                new_ship_doc['parent_id'] = doc_id
                                db.collection("orders").add(new_ship_doc)
                                
                                doc_ref.update({"stock": current_stock - ship_qty})
                            else:
                                # 전량 출고
                                db.collection("orders").document(doc_id).update(update_data)
                        
                        st.success(f"{len(selected_rows)}건 출고 처리 완료!")
                        st.session_state["shipping_key"] += 1
                        st.rerun()
        else:
            st.info("출고 대기 중인 건이 없습니다.")

    with tab2:
        st.subheader("출고 완료 목록")
        
        if "key_ship_done" not in st.session_state:
            st.session_state["key_ship_done"] = 0

        # '출고완료' 상태 조회
        docs = db.collection("orders").where("status", "==", "출고완료").stream()
        rows = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            rows.append(d)
            
        rows.sort(key=lambda x: x.get('shipping_date', datetime.datetime.min), reverse=True)
        
        if rows:
            df = pd.DataFrame(rows)
            if 'shipping_date' in df.columns:
                df['shipping_date'] = df['shipping_date'].apply(lambda x: x.strftime('%Y-%m-%d') if not pd.isnull(x) and hasattr(x, 'strftime') else x)

            col_map = {
                "shipping_date": "출고일", "customer": "발주처", "name": "제품명",
                "stock": "수량", "shipping_method": "배송방법", "shipping_carrier": "배송업체", "shipping_cost": "운임비",
                "delivery_to": "납품처", "delivery_contact": "납품연락처", "delivery_address": "납품주소", "note": "비고"
            }
            display_cols = ["shipping_date", "customer", "name", "stock", "shipping_method", "shipping_carrier", "shipping_cost", "delivery_to", "delivery_contact", "delivery_address", "note"]
            final_cols = [c for c in display_cols if c in df.columns]
            
            st.write("🔽 출고 취소할 항목을 선택하세요.")
            selection = st.dataframe(
                df[final_cols].rename(columns=col_map),
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"ship_done_list_{st.session_state['key_ship_done']}"
            )
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx]
                sel_id = sel_row['id']
                
                st.divider()
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown(f"### 📄 거래명세서 발행: **{sel_row['name']}**")
                    # 거래명세서 HTML 디자인 (간소화)
                    invoice_html = f"""
                    <div style="border:2px solid #333; padding:20px; font-family:sans-serif; background-color:white; color:black;">
                        <h2 style="text-align:center; margin-bottom:30px; text-decoration:underline;">거 래 명 세 서</h2>
                        <table style="width:100%; margin-bottom:20px;">
                            <tr><td style="width:50%;"><strong>공급받는자:</strong> {sel_row.get('customer')} 귀하</td><td style="width:50%; text-align:right;"><strong>일자:</strong> {sel_row.get('shipping_date')}</td></tr>
                        </table>
                        <table style="width:100%; border-collapse:collapse; text-align:center; border:1px solid #333;">
                            <tr style="background-color:#eee;"><th style="border:1px solid #333; padding:8px;">품목</th><th style="border:1px solid #333; padding:8px;">수량</th><th style="border:1px solid #333; padding:8px;">비고</th></tr>
                            <tr>
                                <td style="border:1px solid #333; padding:10px;">{sel_row.get('name')}</td>
                                <td style="border:1px solid #333; padding:10px;">{sel_row.get('stock')} 장</td>
                                <td style="border:1px solid #333; padding:10px;">{sel_row.get('note', '')}</td>
                            </tr>
                        </table>
                    </div>
                    """
                    if st.button("🖨️ 명세서 인쇄 (미리보기)"):
                        st.components.v1.html(invoice_html, height=400, scrolling=True)
                
                with c2:
                    st.markdown("### 🚫 출고 취소")
                    st.warning("상태를 '봉제완료'로 되돌립니다.")
                    if st.button("출고 취소 (봉제완료로 복귀)", type="primary"):
                        db.collection("orders").document(sel_id).update({"status": "봉제완료"})
                        st.success("취소되었습니다.")
                        st.session_state["key_ship_done"] += 1
                        st.rerun()
        else:
            st.info("출고 완료된 내역이 없습니다.")

    with tab3:
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

            stats_carrier = c2.selectbox("배송업체 필터", ["전체"] + shipping_partners)
            stats_customer = c3.text_input("발주처 필터")
            
            st.form_submit_button("통계 조회")
            
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
                    st.markdown(f"##### 📈 {group_label}별 운임비 추이")
                    time_stats = df_stats.groupby('group_key')['shipping_cost'].sum().reset_index()
                    time_stats.columns = [group_label, '운임비']
                    st.bar_chart(time_stats.set_index(group_label))

                # 2. 배송업체별 점유율
                with c_chart2:
                    st.markdown("##### 🚛 배송업체별 운임비 비중")
                    if 'shipping_carrier' in df_stats.columns:
                        carrier_pie = df_stats.groupby('shipping_carrier')['shipping_cost'].sum()
                        st.bar_chart(carrier_pie) # Streamlit 기본 차트 사용

                # 3. 상세 테이블 (업체별)
                if 'shipping_carrier' in df_stats.columns and 'shipping_cost' in df_stats.columns:
                    st.markdown("##### 📋 업체별 상세 지출 현황")
                    carrier_stats = df_stats.groupby(['shipping_carrier', 'customer'])['shipping_cost'].sum().reset_index()
                    # [수정] 컬럼 수 불일치 오류 해결 (3개 컬럼)
                    carrier_stats.columns = ['배송업체', '발주처', '운임비 합계']
                    carrier_stats = carrier_stats.sort_values('운임비 합계', ascending=False)
                    st.dataframe(carrier_stats, use_container_width=True, hide_index=True)
                    
                    st.bar_chart(carrier_stats.set_index('배송업체'))
            else:
                st.info("조회된 배송 내역이 없습니다.")

def render_inventory(db):
    st.header("📦 재고 현황")
    st.info("생산이 완료되어 출고 대기 중인 제품(완제품 재고)을 확인합니다.")
    
    # 재고 기준: status == "봉제완료" (출고 전 단계)
    docs = db.collection("orders").where("status", "==", "봉제완료").stream()
    rows = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        rows.append(d)
    
    if rows:
        df = pd.DataFrame(rows)
        
        # 1. 제품별 재고 요약 (Pivot)
        st.subheader("📊 제품별 재고 요약")
        if 'product_code' in df.columns and 'stock' in df.columns:
            summary = df.groupby(['product_code', 'name']).agg({'stock': 'sum'}).reset_index()
            summary.columns = ['제품코드', '제품명', '총재고수량']
            st.dataframe(summary, use_container_width=True, hide_index=True)
        
        st.divider()
        
        # 2. 상세 재고 내역 (Lot별 관리)
        st.subheader("📋 상세 재고 내역 (Lot별)")
        st.markdown("""
        같은 제품코드라도 **발주번호(Lot)**에 따라 색상, 사양 등이 다를 수 있습니다.  
        아래 목록에서 개별 생산 건별 재고를 확인할 수 있습니다.
        """)
        
        # 날짜 포맷팅
        if 'sewing_end_date' in df.columns:
            df['sewing_end_date'] = df['sewing_end_date'].apply(lambda x: str(x)[:10] if x else "-")
            
        col_map = {
            "product_code": "제품코드", "order_no": "발주번호(Lot)", "name": "제품명", 
            "color": "색상", "stock": "재고수량", "sewing_end_date": "생산완료일",
            "customer": "발주처(용도)", "note": "비고"
        }
        
        display_cols = ["product_code", "order_no", "name", "color", "stock", "customer", "sewing_end_date", "note"]
        final_cols = [c for c in display_cols if c in df.columns]
        
        # 정렬: 제품코드 > 발주번호
        df = df.sort_values(by=['product_code', 'order_no'])
        
        st.dataframe(
            df[final_cols].rename(columns=col_map),
            use_container_width=True,
            hide_index=True
        )
        
    else:
        st.info("현재 보유 중인 완제품 재고가 없습니다. (모두 출고되었거나 생산 중입니다.)")

def render_product_master(db):
    st.header("📦 제품 마스터 관리")
    st.info("제품의 고유한 특성(제품종류, 사종, 중량, 사이즈)을 조합하여 제품 코드를 생성하고 관리합니다.")

    # 제품종류, 사종 기초 코드 가져오기
    # 기초코드설정 메뉴와 동일한 기본값 사용
    default_product_types = [{'name': '세면타올', 'code': 'A'}, {'name': '바스타올', 'code': 'B'}, {'name': '핸드타올', 'code': 'H'}, {'name': '발매트', 'code': 'M'}, {'name': '스포츠타올', 'code': 'S'}]
    default_yarn_types = [{'name': '20수', 'code': '20S'}, {'name': '30수', 'code': '30S'}]
    product_types_coded = get_common_codes("product_types", default_product_types)
    yarn_types_coded = get_common_codes("yarn_types_coded", default_yarn_types)
    weight_codes = get_common_codes("weight_codes", [])
    size_codes = get_common_codes("size_codes", [])

    # 탭 순서 변경: 목록이 먼저 나오도록 수정
    tab1, tab2 = st.tabs(["📋 제품 목록", "➕ 제품 등록"])

    with tab1:
        st.subheader("등록된 제품 목록")
        # created_at 필드가 없는 과거 데이터(P0001 등)도 모두 조회하기 위해 정렬 조건 제거
        product_docs = list(db.collection("products").stream())
        if product_docs:
            products_data = [doc.to_dict() for doc in product_docs]
            df_products = pd.DataFrame(products_data)
            
            col_map = {
                "product_code": "제품코드", "product_type": "제품종류", "yarn_type": "사종",
                "weight": "중량(g)", "size": "사이즈", "created_at": "등록일"
            }
            
            if 'created_at' in df_products.columns:
                # datetime 객체로 변환 (에러 발생 시 NaT 처리)
                df_products['created_at'] = pd.to_datetime(df_products['created_at'], errors='coerce')
                # 문자열 포맷팅 (NaT는 빈 문자열로)
                df_products['created_at'] = df_products['created_at'].dt.strftime('%Y-%m-%d').fillna('')

            # 구버전 데이터 호환
            if "weaving_type" in df_products.columns and "product_type" not in df_products.columns:
                df_products.rename(columns={"weaving_type": "product_type"}, inplace=True)

            # 제품코드 기준 오름차순 정렬
            if 'product_code' in df_products.columns:
                df_products = df_products.sort_values(by='product_code', ascending=True)

            display_cols = ["product_code", "product_type", "yarn_type", "weight", "size", "created_at"]
            final_cols = [c for c in display_cols if c in df_products.columns] # 실제 존재하는 컬럼만 선택
            df_display = df_products[final_cols].rename(columns=col_map)
            
            st.write("🔽 삭제할 제품을 선택(체크)하세요. (다중 선택 가능)")
            selection = st.dataframe(
                df_display, 
                use_container_width=True, 
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="product_list_selection"
            )
            
            # 삭제 기능
            if selection.selection.rows:
                st.divider()
                st.subheader("🗑️ 제품 삭제")
                st.warning(f"선택한 {len(selection.selection.rows)}개의 제품을 삭제하시겠습니까?")
                if st.button("선택한 제품 일괄 삭제", type="primary"):
                    selected_indices = selection.selection.rows
                    selected_rows = df_display.iloc[selected_indices]
                    
                    deleted_cnt = 0
                    for idx, row in selected_rows.iterrows():
                        p_code = row.get("제품코드")
                        if p_code:
                            db.collection("products").document(p_code).delete()
                            deleted_cnt += 1
                    
                    st.success(f"{deleted_cnt}건의 제품이 삭제되었습니다.")
                    st.rerun()
        else:
            st.info("등록된 제품이 없습니다.")

    with tab2:
        st.subheader("신규 제품 등록")

        # 등록 성공 알림 표시 (리런 후에도 유지)
        if "product_reg_msg" in st.session_state:
            st.success(st.session_state["product_reg_msg"])
            del st.session_state["product_reg_msg"]
            
        # [수정] 콤보박스 초기화 로직 (위젯 생성 전에 실행해야 함)
        if st.session_state.get("trigger_reset"):
            st.session_state["reg_pt"] = "선택하세요"
            st.session_state["reg_yt"] = "선택하세요"
            st.session_state["reg_wt"] = "선택하세요"
            st.session_state["reg_sz"] = "선택하세요"
            del st.session_state["trigger_reset"]

        # 기초 코드가 없어도 폼은 보여주되, 경고 메시지 표시
        missing_codes = []
        if not product_types_coded: missing_codes.append("제품 종류")
        if not yarn_types_coded: missing_codes.append("사종")
        if not weight_codes: missing_codes.append("중량")
        if not size_codes: missing_codes.append("사이즈")

        if missing_codes:
            st.warning(f"⚠️ 다음 기초 코드가 등록되지 않았습니다: {', '.join(missing_codes)}\n\n[기초정보관리 > 제품코드설정] 메뉴에서 해당 항목들을 먼저 등록해주세요.")

        # 코드 기준 오름차순 정렬
        if product_types_coded:
            product_types_coded.sort(key=lambda x: x.get('code', ''))
        if yarn_types_coded:
            yarn_types_coded.sort(key=lambda x: x.get('code', ''))
        if weight_codes:
            weight_codes.sort(key=lambda x: x.get('code', ''))
        if size_codes:
            size_codes.sort(key=lambda x: x.get('code', ''))

        # UI에 표시할 이름 목록 (기본값 '선택하세요' 추가)
        product_type_names = ["선택하세요"] + ([item['name'] for item in product_types_coded] if product_types_coded else [])
        yarn_type_names = ["선택하세요"] + ([item['name'] for item in yarn_types_coded] if yarn_types_coded else [])
        weight_names = ["선택하세요"] + ([item['name'] for item in weight_codes] if weight_codes else [])
        size_names = ["선택하세요"] + ([item['name'] for item in size_codes] if size_codes else [])
        # [수정] UI에 표시할 목록 (명칭 + 코드)
        def get_display_opts(items):
            return ["선택하세요"] + ([f"{item['name']} ({item['code']})" for item in items] if items else [])

        product_type_opts = get_display_opts(product_types_coded)
        yarn_type_opts = get_display_opts(yarn_types_coded)
        weight_opts = get_display_opts(weight_codes)
        size_opts = get_display_opts(size_codes)

        c1, c2 = st.columns(2)
        p_product_type_sel = c1.selectbox("제품종류", product_type_opts, key="reg_pt")
        p_yarn_type_sel = c2.selectbox("사종", yarn_type_opts, key="reg_yt")

        c3, c4 = st.columns(2)
        p_weight_sel = c3.selectbox("중량", weight_opts, key="reg_wt")
        p_size_sel = c4.selectbox("사이즈", size_opts, key="reg_sz")

        # 실시간 코드 조합 및 중복 확인
        generated_code = ""
        is_valid = False
            
        # [수정] 선택된 값에서 명칭과 코드 분리
        def parse_selection(val):
            if val == "선택하세요": return "", ""
            try:
                name, code = val.rsplit(' (', 1)
                return name, code[:-1]
            except:
                return val, ""

        pt_name, pt_code = parse_selection(p_product_type_sel)
        yt_name, yt_code = parse_selection(p_yarn_type_sel)
        wt_name, wt_code = parse_selection(p_weight_sel)
        sz_name, sz_code = parse_selection(p_size_sel)

        if "선택하세요" not in [p_product_type_sel, p_yarn_type_sel, p_weight_sel, p_size_sel]:
            if all([pt_code, yt_code, wt_code, sz_code]):
                generated_code = f"{pt_code}{yt_code}{wt_code}{sz_code}"
                
                # 유효성 및 중복 확인
                if len(generated_code) != 10:
                    st.error(f"⚠️ 코드 길이가 10자리가 아닙니다. (현재 {len(generated_code)}자) - [제품코드설정]을 확인하세요.")
                elif db.collection("products").document(generated_code).get().exists:
                    st.error(f"🚫 이미 존재하는 제품코드입니다: **{generated_code}**")
                else:
                    st.success(f"✅ 생성 예정 제품코드: **{generated_code}**")
                    is_valid = True

        if st.button("제품 등록", type="primary", disabled=not is_valid):
            if missing_codes:
                st.error(f"기초 코드가 누락되어 제품을 등록할 수 없습니다: {', '.join(missing_codes)}")
            else:
                product_code = generated_code
                
                # 중량은 계산을 위해 숫자로 변환하여 저장
                try:
                    weight_val = int(wt_code)
                except:
                    weight_val = 0

                product_data = {
                    "product_code": product_code,
                    "product_type": pt_name,
                    "yarn_type": yt_name,
                    "weight": weight_val, # 계산용 숫자 (코드값 사용)
                    "size": sz_name,  # 표시용 이름
                    "created_at": datetime.datetime.now()
                }
                db.collection("products").document(product_code).set(product_data)
                st.session_state["product_reg_msg"] = f"✅ 신규 제품코드 [{product_code}]가 성공적으로 등록되었습니다."
                # 콤보박스 초기화를 위해 리셋 플래그 설정
                st.session_state["trigger_reset"] = True
                st.rerun()

def render_partners(db):
    st.header("🏢 거래처 관리")
    
    # [수정] 탭 순서 변경: 목록 -> 등록 -> 구분 관리
    tab_list, tab_reg, tab_type = st.tabs(["📋 거래처 목록", "➕ 거래처 등록", "⚙️ 거래처 구분 관리"])
    
    # 기초 코드에서 거래처 구분 가져오기
    partner_types = get_common_codes("partner_types", ["발주처", "염색업체", "봉제업체", "배송업체", "기타"])

    with tab_reg:
        with st.form("partner_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            p_type = c1.selectbox("거래처 구분", partner_types)
            p_name = c2.text_input("거래처명", placeholder="상호명 입력")
            
            c1, c2, c3 = st.columns(3)
            p_rep = c1.text_input("대표자명")
            p_biz_num = c2.text_input("사업자번호")
            p_item = c3.text_input("업태/종목")
            
            c1, c2, c3 = st.columns(3)
            p_phone = c1.text_input("전화번호")
            p_fax = c2.text_input("팩스번호")
            p_email = c3.text_input("이메일")
            
            p_address = st.text_input("주소")
            p_account = st.text_input("계좌번호")
            p_note = st.text_area("기타사항")
            
            if st.form_submit_button("거래처 저장"):
                if p_name:
                    db.collection("partners").add({
                        "type": p_type,
                        "name": p_name,
                        "rep_name": p_rep,
                        "biz_num": p_biz_num,
                        "item": p_item,
                        "phone": p_phone,
                        "fax": p_fax,
                        "email": p_email,
                        "address": p_address,
                        "account": p_account,
                        "note": p_note,
                        "reg_date": datetime.datetime.now()
                    })
                    st.success(f"{p_name} 저장 완료!")
                    st.rerun()
                else:
                    st.error("거래처명을 입력해주세요.")

    with tab_list:
        # 거래처 목록 조회
        partners = list(db.collection("partners").order_by("name").stream())
        if partners:
            data = []
            for p in partners:
                p_data = p.to_dict()
                p_data['id'] = p.id
                data.append(p_data)
            df = pd.DataFrame(data)
            
            # 1. 모든 컬럼 보여주기 (빈 값이라도 표시)
            all_cols = ["type", "name", "rep_name", "biz_num", "item", "phone", "fax", "email", "address", "account", "note"]
            
            # 데이터프레임에 없는 컬럼은 빈 문자열로 채움
            for col in all_cols:
                if col not in df.columns:
                    df[col] = ""
            
            # 컬럼명 한글로 변경
            col_map = {
                "type": "구분", "name": "거래처명", "rep_name": "대표자", 
                "biz_num": "사업자번호", "item": "업태/종목", "phone": "전화번호", 
                "fax": "팩스", "email": "이메일", "address": "주소", 
                "account": "계좌번호", "note": "비고"
            }
            
            # 화면 표시용 (id 제외)
            df_display = df[all_cols].rename(columns=col_map)
            
            st.write("🔽 수정할 거래처를 선택하세요.")
            selection = st.dataframe(df_display, use_container_width=True, on_select="rerun", selection_mode="single-row", key="partner_list")
            
            # 엑셀 다운로드
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
            
            st.download_button(
                label="💾 엑셀 다운로드",
                data=buffer.getvalue(),
                file_name="거래처목록.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # 선택 시 수정 폼 표시
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                sel_row = df.iloc[idx] # 화면용 df_display가 아닌 원본 df에서 가져옴 (id 포함)
                sel_id = sel_row['id']
                
                st.divider()
                st.subheader(f"🛠️ 거래처 수정: {sel_row['name']}")
                
                with st.form("edit_partner_form"):
                    c1, c2 = st.columns(2)
                    e_type = c1.selectbox("거래처 구분", partner_types, index=partner_types.index(sel_row['type']) if sel_row['type'] in partner_types else 0)
                    e_name = c2.text_input("거래처명", value=sel_row['name'])
                    
                    c1, c2, c3 = st.columns(3)
                    e_rep = c1.text_input("대표자명", value=sel_row['rep_name'])
                    e_biz = c2.text_input("사업자번호", value=sel_row['biz_num'])
                    e_item = c3.text_input("업태/종목", value=sel_row['item'])
                    
                    c1, c2, c3 = st.columns(3)
                    e_phone = c1.text_input("전화번호", value=sel_row['phone'])
                    e_fax = c2.text_input("팩스번호", value=sel_row['fax'])
                    e_email = c3.text_input("이메일", value=sel_row['email'])
                    
                    e_addr = st.text_input("주소", value=sel_row['address'])
                    e_acc = st.text_input("계좌번호", value=sel_row['account'])
                    e_note = st.text_area("기타사항", value=sel_row['note'])
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("partners").document(sel_id).update({
                            "type": e_type,
                            "name": e_name,
                            "rep_name": e_rep,
                            "biz_num": e_biz,
                            "item": e_item,
                            "phone": e_phone,
                            "fax": e_fax,
                            "email": e_email,
                            "address": e_addr,
                            "account": e_acc,
                            "note": e_note
                        })
                        st.success("수정되었습니다.")
                        st.rerun()
            
            # 2. 거래처 삭제 기능
            st.divider()
            st.subheader("🗑️ 거래처 삭제")
            
            # 이름으로 ID 매핑 (삭제용)
            id_map = {row['name']: row['id'] for row in data}
            delete_list = st.multiselect("삭제할 거래처를 선택하세요", list(id_map.keys()))
            
            if st.button("선택한 거래처 삭제"):
                if delete_list:
                    for name in delete_list:
                        db.collection("partners").document(id_map[name]).delete()
                    st.success("삭제되었습니다.")
                    st.rerun()
        else:
            st.info("등록된 거래처가 없습니다.")

    with tab_type:
        st.subheader("거래처 구분 관리")
        st.info("거래처 등록 시 사용할 구분을 관리합니다.")
        manage_code("partner_types", partner_types, "거래처 구분")

def render_machines(db):
    st.header("🏭 제직기 관리")
    
    # [수정] 탭 순서 변경: 목록 -> 등록
    tab_list, tab_reg = st.tabs(["📋 제직기 목록", "➕ 제직기 등록"])
    
    with tab_reg:
        st.subheader("제직기 등록 및 수정")
        st.info("호기 번호가 같으면 기존 정보가 수정(덮어쓰기)됩니다.")
        
        with st.form("add_machine_form_new"):
            c1, c2 = st.columns(2)
            new_no = c1.number_input("호기 번호 (No.)", min_value=1, step=1, help="정렬 순서 및 고유 ID로 사용됩니다.")
            new_name = c2.text_input("제직기 명칭", placeholder="예: 1호대")
            c3, c4, c5 = st.columns(3)
            new_model = c3.text_input("모델명")
            new_loom = c4.text_input("직기타입")
            new_jacquard = c5.text_input("자가드타입")
            new_note = st.text_input("특이사항/메모")
            
            if st.form_submit_button("저장"):
                db.collection("machines").document(str(new_no)).set({
                    "machine_no": new_no,
                    "name": new_name,
                    "model": new_model,
                    "loom_type": new_loom,
                    "jacquard_type": new_jacquard,
                    "note": new_note
                })
                st.success("저장되었습니다.")
                st.rerun()

    with tab_list:
        st.subheader("제직기 목록")
        machines_ref = db.collection("machines").order_by("machine_no")
        m_docs = list(machines_ref.stream())
        m_list = []
        for d in m_docs:
            item = d.to_dict()
            item['id'] = d.id
            m_list.append(item)
        
        if not m_list:
            st.warning("등록된 제직기가 없습니다.")
            if st.button("기본 제직기(1~9호대) 자동 생성"):
                for i in range(1, 10):
                    db.collection("machines").document(str(i)).set({
                        "machine_no": i,
                        "name": f"{i}호대",
                        "model": "",
                        "note": ""
                    })
                st.success("기본 제직기가 생성되었습니다.")
                st.rerun()
        else:
            df = pd.DataFrame(m_list)
            col_map = {"machine_no": "호기", "name": "명칭", "model": "모델명", "note": "비고"}
            # 신규 컬럼이 없는 경우를 대비해 빈 값으로 초기화
            for col in ["loom_type", "jacquard_type"]:
                if col not in df.columns:
                    df[col] = ""
            col_map = {"machine_no": "호기", "name": "명칭", "model": "모델명", "loom_type": "직기타입", "jacquard_type": "자가드타입", "note": "비고"}
            
            # 화면 표시용
            df_display = df[["machine_no", "name", "model", "loom_type", "jacquard_type", "note"]].rename(columns=col_map)
            
            st.write("🔽 수정할 제직기를 선택하세요.")
            selection = st.dataframe(df_display, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="machine_list")
            
            # 엑셀 다운로드
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_display.to_excel(writer, index=False)
            st.download_button(label="💾 엑셀 다운로드", data=buffer.getvalue(), file_name="제직기목록.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            if selection.selection.rows:
                idx = selection.selection.rows[0]
                # DataFrame 대신 원본 리스트 사용 (KeyError 방지)
                sel_item = m_list[idx]
                sel_id = sel_item['id']
                
                st.divider()
                st.subheader(f"🛠️ 제직기 수정: {sel_item['name']}")
                
                with st.form("edit_machine_form"):
                    c1, c2 = st.columns(2)
                    e_no = c1.number_input("호기 번호", value=int(sel_item['machine_no']), step=1, disabled=True)
                    e_name = c2.text_input("명칭", value=sel_item['name'])
                    c3, c4, c5 = st.columns(3)
                    e_model = c3.text_input("모델명", value=sel_item.get('model', ''))
                    e_loom = c4.text_input("직기타입", value=sel_item.get('loom_type', ''))
                    e_jacquard = c5.text_input("자가드타입", value=sel_item.get('jacquard_type', ''))
                    e_note = st.text_input("비고", value=sel_item.get('note', ''))
                    
                    if st.form_submit_button("수정 저장"):
                        db.collection("machines").document(sel_id).update({
                            "name": e_name, 
                            "model": e_model, 
                            "loom_type": e_loom,
                            "jacquard_type": e_jacquard,
                            "note": e_note
                        })
                        st.success("수정되었습니다.")
                        st.rerun()
                
                if st.button("🗑️ 이 제직기 삭제", type="primary"):
                    db.collection("machines").document(sel_id).delete()
                    st.success("삭제되었습니다.")
                    st.rerun()

def render_codes(db):
    st.header("📝 제품코드 설정")
    st.info("제품 코드 생성을 위한 각 부분의 코드 및 포맷을 설정합니다.")

    # [수정] 색번 탭 제거 (염색현황으로 이동)
    tab1, tab2, tab3, tab4 = st.tabs(["제품 종류", "사종", "중량", "사이즈"])

    with tab1:
        manage_code_with_code("product_types", [{'name': '세면타올', 'code': 'A'}, {'name': '바스타올', 'code': 'B'}, {'name': '핸드타올', 'code': 'H'}, {'name': '발매트', 'code': 'M'}, {'name': '스포츠타올', 'code': 'S'}], "제품 종류")
    
    with tab2:
        manage_code_with_code("yarn_types_coded", [{'name': '20수', 'code': '20S'}, {'name': '30수', 'code': '30S'}], "사종")

    with tab3:
        manage_code_with_code("weight_codes", [], "중량")

    with tab4:
        manage_code_with_code("size_codes", [], "사이즈")

def render_users(db):
    st.header("👤 사용자 관리")
    if st.session_state.get("role") != "admin":
        st.error("관리자 권한이 필요합니다.")
    else:
        st.info("시스템 사용자를 등록하고 권한을 설정합니다.")
        
        tab1, tab2 = st.tabs(["📋 사용자 목록", "➕ 사용자 등록"])
        
        all_menus = ["발주서접수", "발주현황", "제직현황", "염색현황", "봉제현황", "출고현황", "재고현황", "제품 관리", "거래처관리", "제직기관리", "제품코드설정", "사용자 관리"]
        
        with tab1:
            # 사용자 목록 조회
            users_ref = db.collection("users").stream()
            users_list = []
            for doc in users_ref:
                u = doc.to_dict()
                u['id'] = doc.id # 문서 ID를 식별자로 사용
                users_list.append(u)
            
            if users_list:
                df_users = pd.DataFrame(users_list)
                # 표시할 컬럼 정리
                display_cols = ["username", "name", "role", "department", "phone", "permissions"]
                for c in display_cols:
                    if c not in df_users.columns: df_users[c] = ""
                
                st.write("🔽 수정할 사용자를 선택하세요.")
                selection = st.dataframe(
                    df_users[display_cols],
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="user_list"
                )
                
                if selection.selection.rows:
                    idx = selection.selection.rows[0]
                    sel_user = df_users.iloc[idx]
                    sel_uid = sel_user['username']
                    
                    st.divider()
                    st.subheader(f"🛠️ 사용자 수정: {sel_user['name']} ({sel_uid})")
                    
                    with st.form("edit_user_form"):
                        c1, c2 = st.columns(2)
                        e_name = c1.text_input("이름", value=sel_user['name'])
                        e_role = c2.selectbox("권한(Role)", ["admin", "user"], index=0 if sel_user['role']=="admin" else 1)
                        
                        c3, c4 = st.columns(2)
                        e_dept = c3.text_input("부서/직책", value=sel_user.get('department', ''))
                        e_phone = c4.text_input("연락처", value=sel_user.get('phone', ''))
                        
                        # 권한 설정
                        current_perms = sel_user['permissions'] if isinstance(sel_user['permissions'], list) else []
                        e_perms = st.multiselect("접근 가능 메뉴", all_menus, default=[p for p in current_perms if p in all_menus])
                        
                        new_pw = st.text_input("비밀번호 변경 (비워두면 유지)", type="password")
                        
                        if st.form_submit_button("수정 저장"):
                            updates = {
                                "name": e_name, "role": e_role, "department": e_dept, "phone": e_phone, "permissions": e_perms
                            }
                            if new_pw:
                                updates["password"] = new_pw
                            
                            db.collection("users").document(sel_uid).update(updates)
                            st.success("사용자 정보가 수정되었습니다.")
                            st.rerun()
                    
                    if st.button("🗑️ 사용자 삭제", type="primary"):
                        if sel_uid == "admin":
                            st.error("admin 계정은 삭제할 수 없습니다.")
                        else:
                            db.collection("users").document(sel_uid).delete()
                            st.success("삭제되었습니다.")
                            st.rerun()
            else:
                st.info("등록된 사용자가 없습니다.")
        
        with tab2:
            st.subheader("신규 사용자 등록")
            with st.form("add_user_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                u_id = c1.text_input("아이디 (ID)")
                u_pw = c2.text_input("비밀번호", type="password")
                c3, c4 = st.columns(2)
                u_name = c3.text_input("이름")
                u_role = c4.selectbox("권한", ["user", "admin"])
                c5, c6 = st.columns(2)
                u_dept = c5.text_input("부서/직책")
                u_phone = c6.text_input("연락처")
                u_perms = st.multiselect("접근 가능 메뉴", all_menus, default=["발주서접수", "발주현황"])
                
                if st.form_submit_button("사용자 등록"):
                    if u_id and u_pw and u_name:
                        if db.collection("users").document(u_id).get().exists:
                            st.error("이미 존재하는 아이디입니다.")
                        else:
                            db.collection("users").document(u_id).set({
                                "username": u_id, "password": u_pw, "name": u_name, "role": u_role,
                                "department": u_dept, "phone": u_phone, "permissions": u_perms,
                                "created_at": datetime.datetime.now()
                            })
                            st.success(f"사용자 {u_name}({u_id}) 등록 완료!"); st.rerun()
                    else:
                        st.warning("아이디, 비밀번호, 이름은 필수 입력입니다.")