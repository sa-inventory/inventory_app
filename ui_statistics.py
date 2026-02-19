import streamlit as st
import pandas as pd
import datetime
import io
import calendar
import altair as alt
try: # type: ignore
    import matplotlib.pyplot as plt # type: ignore
except ImportError:
    plt = None
import base64
import platform
from firebase_admin import firestore
from utils import get_partners, generate_report_html

# [NEW] Matplotlib 한글 폰트 설정
@st.cache_resource
def setup_matplotlib_font():
    if plt:
        system_name = platform.system()
        if system_name == 'Windows':
            plt.rc('font', family='Malgun Gothic')
        elif system_name == 'Darwin': # Mac
            plt.rc('font', family='AppleGothic')
        else: # Linux
            try:
                from matplotlib import font_manager # type: ignore
                font_manager.fontManager.addfont('/usr/share/fonts/truetype/nanum/NanumGothic.ttf')
                plt.rc('font', family='NanumGothic')
            except:
                pass
        plt.rcParams['axes.unicode_minus'] = False

def render_statistics(db, sub_menu):
    st.header(sub_menu)
    st.info("발주부터 출고까지 전 공정의 현황을 년도별/월별/기간별로 분석합니다.")
    
    # --- 공통 조회 조건 ---
    with st.expander("조회 조건 설정", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        stat_type = c1.radio("분석 기준", ["기간별", "월별", "년도별"], horizontal=True)
        
        start_dt, end_dt = None, None
        
        if stat_type == "기간별":
            today = datetime.date.today()
            date_range = c2.date_input("조회 기간", [today - datetime.timedelta(days=30), today])
            if len(date_range) == 2:
                start_dt = datetime.datetime.combine(date_range[0], datetime.time.min)
                end_dt = datetime.datetime.combine(date_range[1], datetime.time.max)
        elif stat_type == "월별":
            cc1, cc2 = c2.columns(2)
            this_year = datetime.date.today().year
            sel_year = cc1.number_input("년도", value=this_year, step=1, format="%d")
            sel_month_str = cc2.selectbox("월", ["전체"] + [f"{i}월" for i in range(1, 13)])
            
            if sel_month_str == "전체":
                start_dt = datetime.datetime(sel_year, 1, 1)
                end_dt = datetime.datetime(sel_year, 12, 31, 23, 59, 59)
            else:
                sel_month = int(sel_month_str.replace("월", ""))
                last_day = calendar.monthrange(sel_year, sel_month)[1]
                start_dt = datetime.datetime(sel_year, sel_month, 1)
                end_dt = datetime.datetime(sel_year, sel_month, last_day, 23, 59, 59)
        else: # 년도별
            cc1, cc2 = c2.columns(2)
            this_year = datetime.date.today().year
            start_year = cc1.number_input("시작 년도", value=this_year-4, step=1, format="%d")
            end_year = cc2.number_input("종료 년도", value=this_year, step=1, format="%d")
            
            start_dt = datetime.datetime(start_year, 1, 1)
            end_dt = datetime.datetime(end_year, 12, 31, 23, 59, 59)

        all_partners = get_partners()
        filter_partners = c3.multiselect("거래처/업체명 필터 (다중선택)", all_partners)

        # [NEW] 그래프 옵션
        chart_type_opt = c4.radio("그래프 형태", ["막대형", "선형(점)"], horizontal=True)
        include_chart_print = c4.checkbox("인쇄 시 그래프 포함", value=True)

    # --- 데이터 로드 ---
    # 데이터 양이 많아지면 쿼리 최적화 필요
    @st.cache_data(ttl=60)
    def load_all_orders():
        docs = db.collection("orders").stream()
        data = []
        for doc in docs:
            d = doc.to_dict()
            d['id'] = doc.id
            # 날짜 필드들 datetime 변환
            for date_col in ['date', 'weaving_end_time', 'dyeing_in_date', 'sewing_end_date', 'shipping_date']:
                if d.get(date_col):
                    if isinstance(d[date_col], str):
                        try: d[date_col] = pd.to_datetime(d[date_col])
                        except: d[date_col] = None
                    elif hasattr(d[date_col], 'tzinfo'):
                        d[date_col] = d[date_col].replace(tzinfo=None)
            data.append(d)
        return pd.DataFrame(data)

    df = load_all_orders()
    
    if df.empty:
        st.warning("데이터가 없습니다.")
        return

    # 공통 그룹화 키 생성 함수
    def get_group_key(row, date_col):
        if pd.isna(row.get(date_col)): return None
        dt = row[date_col]
        if stat_type == "기간별": return dt.strftime("%Y-%m-%d")
        elif stat_type == "월별": return dt.strftime("%Y-%m")
        else: return dt.strftime("%Y")

    # 공통 액션 버튼 (엑셀/인쇄)
    def show_actions(df_data, file_name, title, chart_col=None):
        # [NEW] 인쇄 옵션 설정
        with st.expander(f"인쇄 옵션 ({title})"):
            po_c1, po_c2, po_c3, po_c4 = st.columns(4)
            p_title = po_c1.text_input("제목", value=title, key=f"p_title_{file_name}")
            p_title_size = po_c2.number_input("제목 크기(px)", value=24, step=1, key=f"p_ts_{file_name}")
            p_body_size = po_c3.number_input("본문 글자 크기(px)", value=11, step=1, key=f"p_bs_{file_name}")
            p_padding = po_c4.number_input("셀 여백(px)", value=6, step=1, key=f"p_pad_{file_name}")
            
            po_c5, po_c6, po_c7 = st.columns(3)
            p_show_date = po_c5.checkbox("출력일시 표시", value=True, key=f"p_sd_{file_name}")
            p_date_pos = po_c6.selectbox("일시 위치", ["Right", "Left", "Center"], index=0, key=f"p_dp_{file_name}")
            p_date_size = po_c7.number_input("일시 글자 크기(px)", value=12, step=1, key=f"p_ds_{file_name}")
            
            st.caption("페이지 여백 (mm)")
            po_c8, po_c9, po_c10, po_c11 = st.columns(4)
            p_m_top = po_c8.number_input("상단", value=15, step=1, key=f"p_mt_{file_name}")
            p_m_bottom = po_c9.number_input("하단", value=15, step=1, key=f"p_mb_{file_name}")
            p_m_left = po_c10.number_input("좌측", value=15, step=1, key=f"p_ml_{file_name}")
            p_m_right = po_c11.number_input("우측", value=15, step=1, key=f"p_mr_{file_name}")

        c_btn1, c_btn2 = st.columns([1, 1])
        
        # Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_data.to_excel(writer, index=False)
        c_btn1.download_button("💾 엑셀 다운로드", buffer.getvalue(), f"{file_name}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        # Print
        if c_btn2.button("🖨️ 인쇄", key=f"print_{file_name}"):
            # [NEW] 인쇄 시 폰트 설정 함수 호출
            setup_matplotlib_font()

            chart_html = ""
            # 그래프 인쇄 옵션이 켜져있고, 그릴 데이터 컬럼이 지정된 경우
            if include_chart_print and chart_col and not df_data.empty and plt:
                try:
                    # Matplotlib을 사용하여 정적 이미지 생성
                    plt.figure(figsize=(10, 4))
                    
                    plt.rcParams['axes.unicode_minus'] = False

                    x = df_data.iloc[:, 0].astype(str) # 첫 번째 컬럼(그룹키)을 X축으로
                    y = df_data[chart_col]

                    if chart_type_opt == "막대형":
                        plt.bar(x, y, color='#4c78a8')
                    else:
                        plt.plot(x, y, marker='o', linewidth=2, markersize=8, color='#f58518')

                    plt.title(p_title) # Use the title from the input
                    plt.xticks(rotation=45, ha='right')
                    plt.grid(axis='y', linestyle='--', alpha=0.7)
                    plt.tight_layout()

                    img_buf = io.BytesIO()
                    plt.savefig(img_buf, format='png')
                    img_buf.seek(0)
                    b64_data = base64.b64encode(img_buf.read()).decode('utf-8')
                    chart_html = f'<img src="data:image/png;base64,{b64_data}" style="width:100%; margin-bottom: 20px;">'
                    plt.close()
                except Exception as e:
                    st.warning(f"그래프 생성 실패: {e}")

            options = {
                'mt': p_m_top, 'mr': p_m_right, 'mb': p_m_bottom, 'ml': p_m_left,
                'ts': p_title_size, 'bs': p_body_size, 'pad': p_padding,
                'da': p_date_pos.lower(), 'ds': p_date_size, 'dd': "block" if p_show_date else "none"
            }
            html = generate_report_html(p_title, df_data, "", options, chart_html)
            st.components.v1.html(html, height=0, width=0)

    # --- 1. 발주내역 ---
    if sub_menu == "발주내역":
        st.subheader("발주 수량 및 건수 통계")
        df_order = df.copy()
        if start_dt and end_dt:
            df_order = df_order[(df_order['date'] >= start_dt) & (df_order['date'] <= end_dt)]
        
        if filter_partners:
            df_order = df_order[df_order['customer'].isin(filter_partners)]

        if not df_order.empty:
            # --- 요약 ---
            total_orders = df_order['order_no'].nunique()
            total_qty = df_order['stock'].sum()
            avg_qty = total_qty / total_orders if total_orders > 0 else 0
            
            m1, m2, m3 = st.columns(3)
            m1.metric("총 발주건수", f"{total_orders:,} 건")
            m2.metric("총 발주수량", f"{total_qty:,} 장")
            m3.metric("건당 평균수량", f"{avg_qty:,.1f} 장")
            st.divider()

            df_order['group_key'] = df_order.apply(lambda x: get_group_key(x, 'date'), axis=1)
            group_label = stat_type.replace('별', '')
            
            # 1. 상단: 거래처별 통계 및 선택 (먼저 처리하여 필터링 기준 마련)
            st.write(f"**거래처별 발주 현황**")
            partner_stats = df_order.groupby('customer').agg(발주건수=('order_no', 'nunique'), 총수량=('stock', 'sum')).reset_index()
            partner_stats['평균수량'] = partner_stats['총수량'] / partner_stats['발주건수']
            partner_stats = partner_stats.sort_values('총수량', ascending=False)
            
            partner_stats['선택'] = False
            edited_partner_stats = st.data_editor(
                partner_stats,
                column_order=["선택", "customer", "총수량", "발주건수", "평균수량"],
                column_config={"선택": st.column_config.CheckboxColumn(default=False)},
                disabled=['customer', '총수량', '발주건수', '평균수량'],
                width="stretch", hide_index=True, key="order_partner_selector"
            )
            selected_customers = edited_partner_stats[edited_partner_stats['선택']]['customer'].tolist()
            show_actions(partner_stats.drop(columns=['선택']), "발주처별_통계", "발주처별 수량 통계", chart_col='총수량')
            
            # [NEW] 비교 모드 토글
            compare_mode = st.toggle("업체별 비교", key="order_compare")

            st.divider()

            # 2. 데이터 필터링
            if selected_customers:
                df_chart = df_order[df_order['customer'].isin(selected_customers)].copy()
            else:
                df_chart = df_order.copy()

            # 3. 하단: 시계열 차트 (필터링된 데이터 기반)
            st.write(f"**{group_label}별 발주 추이**")
            
            # 비교 모드에 따라 그룹화 방식 변경
            if compare_mode and selected_customers:
                group_cols = ['group_key', 'customer']
                chart_color_col = alt.Color('customer:N', title="발주처")
            else:
                group_cols = ['group_key']
                chart_color_col = alt.value('#4c78a8') # 단일 색상

            time_stats = df_chart.groupby(group_cols).agg(총수량=('stock', 'sum')).reset_index().rename(columns={'group_key': group_label})

            # Altair 차트 생성
            base = alt.Chart(time_stats).encode(x=alt.X(f'{group_label}:N', axis=alt.Axis(labelAngle=-45), sort=None), y='총수량:Q', color=chart_color_col, tooltip=[alt.Tooltip(f'{group_label}:N', title=group_label), alt.Tooltip('customer:N', title='발주처') if compare_mode else alt.Tooltip(), alt.Tooltip('총수량:Q', title='총수량', format=',')])
            if chart_type_opt == "막대형":
                chart = base.mark_bar(opacity=0.8).encode(xOffset='customer:N' if compare_mode else alt.XOffset())
            else:
                chart = base.mark_line(point=alt.OverlayMarkDef(size=100, filled=True))
            
            st.dataframe(time_stats, width="stretch", hide_index=True)
            with st.expander("📈 그래프 보기", expanded=True):
                st.altair_chart(chart, use_container_width=True)
            show_actions(time_stats, f"발주추이_{group_label}", f"{group_label}별 발주 추이", chart_col='총수량')
        else:
            st.info("조회된 데이터가 없습니다.")

    # --- 2. 제직내역 ---
    elif sub_menu == "제직내역":
        st.subheader("제직 생산량 통계")
        df_weav = df.dropna(subset=['weaving_end_time']).copy()
        if start_dt and end_dt:
            df_weav = df_weav[(df_weav['weaving_end_time'] >= start_dt) & (df_weav['weaving_end_time'] <= end_dt)]
        
        if filter_partners:
            df_weav = df_weav[df_weav['customer'].isin(filter_partners)]

        if not df_weav.empty:
            # --- 요약 ---
            total_rolls = len(df_weav)
            total_qty = df_weav['real_stock'].sum()
            total_weight = df_weav['prod_weight_kg'].sum()
            
            m1, m2, m3 = st.columns(3)
            m1.metric("총 생산롤수", f"{total_rolls:,} 롤")
            m2.metric("총 생산매수", f"{total_qty:,} 장")
            m3.metric("총 생산중량", f"{total_weight:,.1f} kg")
            st.divider()

            df_weav['group_key'] = df_weav.apply(lambda x: get_group_key(x, 'weaving_end_time'), axis=1)
            group_label = stat_type.replace('별', '')
            
            # 1. 상단: 제직기별 통계 및 선택
            st.write("**제직기별 생산량**")
            if 'machine_no' in df_weav.columns:
                machine_stats = df_weav.groupby('machine_no').agg(생산롤수=('id', 'count'), 총생산매수=('real_stock', 'sum'), 총생산중량=('prod_weight_kg', 'sum')).sort_values('총생산매수', ascending=False).reset_index()
            else:
                machine_stats = pd.DataFrame(columns=['machine_no', '생산롤수', '총생산매수', '총생산중량'])

            machine_stats['선택'] = False
            edited_machine_stats = st.data_editor(
                machine_stats,
                column_order=["선택", "machine_no", "총생산매수", "생산롤수", "총생산중량"],
                column_config={"선택": st.column_config.CheckboxColumn(default=False)},
                disabled=['machine_no', '총생산매수', '생산롤수', '총생산중량'],
                width="stretch", hide_index=True, key="weaving_machine_selector"
            )
            selected_machines = edited_machine_stats[edited_machine_stats['선택']]['machine_no'].tolist()
            show_actions(machine_stats.drop(columns=['선택']), "제직기별_생산통계", "제직기별 생산량 통계", chart_col='총생산매수')

            # [NEW] 비교 모드 토글
            compare_mode = st.toggle("제직기별 비교", key="weaving_compare")

            st.divider()

            # 2. 데이터 필터링
            if selected_machines:
                df_chart = df_weav[df_weav['machine_no'].isin(selected_machines)].copy()
            else:
                df_chart = df_weav.copy()

            # 3. 하단: 시계열 차트
            st.write(f"**{group_label}별 생산량 추이**")
            
            if compare_mode and selected_machines:
                group_cols = ['group_key', 'machine_no']
                chart_color_col = alt.Color('machine_no:N', title="제직기", scale=alt.Scale(scheme='category10'))
            else:
                group_cols = ['group_key']
                chart_color_col = alt.value('#4c78a8')

            time_stats = df_chart.groupby(group_cols).agg(총생산매수=('real_stock', 'sum')).reset_index().rename(columns={'group_key': group_label})

            base = alt.Chart(time_stats).encode(x=alt.X(f'{group_label}:N', axis=alt.Axis(labelAngle=-45), sort=None), y='총생산매수:Q', color=chart_color_col, tooltip=[alt.Tooltip(f'{group_label}:N', title=group_label), alt.Tooltip('machine_no:N', title='제직기') if compare_mode else alt.Tooltip(), alt.Tooltip('총생산매수:Q', title='총생산매수', format=',')])
            if chart_type_opt == "막대형":
                chart = base.mark_bar(opacity=0.8).encode(xOffset='machine_no:N' if compare_mode else alt.XOffset())
            else:
                chart = base.mark_line(point=alt.OverlayMarkDef(size=100, filled=True))
                
            st.dataframe(time_stats, width="stretch", hide_index=True)
            with st.expander("📈 그래프 보기", expanded=True):
                st.altair_chart(chart, use_container_width=True)
            show_actions(time_stats, f"생산추이_{group_label}", f"{group_label}별 생산량 추이", chart_col='총생산매수')
        else:
            st.info("조회된 데이터가 없습니다.")

    # --- 3. 염색내역 ---
    elif sub_menu == "염색내역":
        st.subheader("염색 입고 및 비용 통계")
        df_dye = df.dropna(subset=['dyeing_in_date']).copy()
        if start_dt and end_dt:
            df_dye = df_dye[(df_dye['dyeing_in_date'] >= start_dt) & (df_dye['dyeing_in_date'] <= end_dt)]
        
        if filter_partners:
            df_dye = df_dye[df_dye['dyeing_partner'].isin(filter_partners) | df_dye['customer'].isin(filter_partners)]

        if not df_dye.empty:
            # --- 요약 ---
            total_jobs = len(df_dye)
            total_qty = df_dye['stock'].sum()
            total_amount = df_dye['dyeing_amount'].sum()
            
            m1, m2, m3 = st.columns(3)
            m1.metric("총 작업건수", f"{total_jobs:,} 건")
            m2.metric("총 입고수량", f"{total_qty:,} 장")
            m3.metric("총 염색비용", f"{total_amount:,} 원")
            st.divider()

            df_dye['group_key'] = df_dye.apply(lambda x: get_group_key(x, 'dyeing_in_date'), axis=1)
            group_label = stat_type.replace('별', '')
            
            # 1. 상단: 업체별 통계 및 선택
            st.write("**업체별 실적**")
            partner_stats = df_dye.groupby('dyeing_partner').agg(작업건수=('id', 'count'), 총수량=('stock', 'sum'), 총금액=('dyeing_amount', 'sum')).sort_values('총금액', ascending=False).reset_index()

            partner_stats['선택'] = False
            edited_partner_stats = st.data_editor(
                partner_stats,
                column_order=["선택", "dyeing_partner", "총금액", "총수량", "작업건수"],
                column_config={"선택": st.column_config.CheckboxColumn(default=False)},
                disabled=['dyeing_partner', '총금액', '총수량', '작업건수'],
                width="stretch", hide_index=True, key="dyeing_partner_selector"
            )
            selected_partners = edited_partner_stats[edited_partner_stats['선택']]['dyeing_partner'].tolist()
            show_actions(partner_stats.drop(columns=['선택']), "염색업체별_실적", "염색업체별 실적 및 비용", chart_col='총금액')

            # [NEW] 비교 모드 토글
            compare_mode = st.toggle("업체별 비교", key="dyeing_compare")

            st.divider()

            # 2. 데이터 필터링
            if selected_partners:
                df_chart = df_dye[df_dye['dyeing_partner'].isin(selected_partners)].copy()
            else:
                df_chart = df_dye.copy()

            # 3. 하단: 시계열 차트
            st.write(f"**{group_label}별 염색 비용 추이**")
            
            if compare_mode and selected_partners:
                group_cols = ['group_key', 'dyeing_partner']
                chart_color_col = alt.Color('dyeing_partner:N', title="염색업체")
            else:
                group_cols = ['group_key']
                chart_color_col = alt.value('#4c78a8')

            time_stats = df_chart.groupby(group_cols).agg(총금액=('dyeing_amount', 'sum')).reset_index().rename(columns={'group_key': group_label})

            base = alt.Chart(time_stats).encode(x=alt.X(f'{group_label}:N', axis=alt.Axis(labelAngle=-45), sort=None), y='총금액:Q', color=chart_color_col, tooltip=[alt.Tooltip(f'{group_label}:N', title=group_label), alt.Tooltip('dyeing_partner:N', title='염색업체') if compare_mode else alt.Tooltip(), alt.Tooltip('총금액:Q', title='총금액', format=',')])
            if chart_type_opt == "막대형":
                chart = base.mark_bar(opacity=0.8).encode(xOffset='dyeing_partner:N' if compare_mode else alt.XOffset())
            else:
                chart = base.mark_line(point=alt.OverlayMarkDef(size=100, filled=True))

            st.dataframe(time_stats, width="stretch", hide_index=True)
            with st.expander("📈 그래프 보기", expanded=True):
                st.altair_chart(chart, use_container_width=True)
            show_actions(time_stats, f"염색비용추이_{group_label}", f"{group_label}별 염색 비용 추이", chart_col='총금액')
        else:
            st.info("조회된 데이터가 없습니다.")

    # --- 4. 봉제내역 ---
    elif sub_menu == "봉제내역":
        st.subheader("봉제 생산 및 비용 통계")
        df_sew = df.dropna(subset=['sewing_end_date']).copy()
        if start_dt and end_dt:
            df_sew = df_sew[(df_sew['sewing_end_date'] >= start_dt) & (df_sew['sewing_end_date'] <= end_dt)]
        
        if filter_partners:
            df_sew = df_sew[df_sew['sewing_partner'].isin(filter_partners) | df_sew['customer'].isin(filter_partners)]

        if not df_sew.empty:
            # --- 요약 ---
            total_jobs = len(df_sew)
            total_qty = df_sew['stock'].sum()
            total_defect = df_sew['sewing_defect_qty'].sum() if 'sewing_defect_qty' in df_sew.columns else 0
            total_amount = df_sew['sewing_amount'].sum() if 'sewing_amount' in df_sew.columns else 0
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("총 작업건수", f"{total_jobs:,} 건")
            m2.metric("총 생산수량", f"{total_qty:,} 장")
            m3.metric("총 불량수량", f"{total_defect:,} 장")
            m4.metric("총 외주비용", f"{total_amount:,} 원")
            st.divider()

            df_sew['group_key'] = df_sew.apply(lambda x: get_group_key(x, 'sewing_end_date'), axis=1)
            group_label = stat_type.replace('별', '')
            
            # 1. 상단: 업체별 통계 및 선택
            st.write("**업체별 실적 및 비용**")
            partner_stats = df_sew.groupby('sewing_partner').agg(작업건수=('id', 'count'), 총생산수량=('stock', 'sum'), 총불량수량=('sewing_defect_qty', 'sum'), 총비용=('sewing_amount', 'sum')).sort_values('총생산수량', ascending=False).reset_index()

            partner_stats['선택'] = False
            edited_partner_stats = st.data_editor(
                partner_stats,
                column_order=["선택", "sewing_partner", "총생산수량", "총비용", "작업건수", "총불량수량"],
                column_config={"선택": st.column_config.CheckboxColumn(default=False)},
                disabled=['sewing_partner', '총생산수량', '총비용', '작업건수', '총불량수량'],
                width="stretch", hide_index=True, key="sewing_partner_selector"
            )
            selected_partners = edited_partner_stats[edited_partner_stats['선택']]['sewing_partner'].tolist()
            show_actions(partner_stats.drop(columns=['선택']), "봉제업체별_실적", "봉제업체별 실적 및 비용", chart_col='총생산수량')

            # [NEW] 비교 모드 토글
            compare_mode = st.toggle("업체별 비교", key="sewing_compare")

            st.divider()

            # 2. 데이터 필터링
            if selected_partners:
                df_chart = df_sew[df_sew['sewing_partner'].isin(selected_partners)].copy()
            else:
                df_chart = df_sew.copy()

            # 3. 하단: 시계열 차트
            st.write(f"**{group_label}별 봉제 수량 추이**")
            
            if compare_mode and selected_partners:
                group_cols = ['group_key', 'sewing_partner']
                chart_color_col = alt.Color('sewing_partner:N', title="봉제업체")
            else:
                group_cols = ['group_key']
                chart_color_col = alt.value('#4c78a8')

            time_stats = df_chart.groupby(group_cols).agg(총생산수량=('stock', 'sum')).reset_index().rename(columns={'group_key': group_label})

            base = alt.Chart(time_stats).encode(x=alt.X(f'{group_label}:N', axis=alt.Axis(labelAngle=-45), sort=None), y='총생산수량:Q', color=chart_color_col, tooltip=[alt.Tooltip(f'{group_label}:N', title=group_label), alt.Tooltip('sewing_partner:N', title='봉제업체') if compare_mode else alt.Tooltip(), alt.Tooltip('총생산수량:Q', title='총생산수량', format=',')])
            if chart_type_opt == "막대형":
                chart = base.mark_bar(opacity=0.8).encode(xOffset='sewing_partner:N' if compare_mode else alt.XOffset())
            else:
                chart = base.mark_line(point=alt.OverlayMarkDef(size=100, filled=True))

            st.dataframe(time_stats, width="stretch", hide_index=True)
            with st.expander("📈 그래프 보기", expanded=True):
                st.altair_chart(chart, use_container_width=True)
            show_actions(time_stats, f"봉제수량추이_{group_label}", f"{group_label}별 봉제 수량 추이", chart_col='총생산수량')
        else:
            st.info("조회된 데이터가 없습니다.")

    # --- 5. 출고/운임내역 ---
    elif sub_menu == "출고/운임내역":
        st.subheader("출고 실적 및 운임비 통계")
        df_ship = df.dropna(subset=['shipping_date']).copy()
        if start_dt and end_dt:
            df_ship = df_ship[(df_ship['shipping_date'] >= start_dt) & (df_ship['shipping_date'] <= end_dt)]
        
        if filter_partners:
            # 배송업체 또는 발주처 검색
            df_ship = df_ship[
                df_ship['shipping_carrier'].isin(filter_partners) | 
                df_ship['customer'].isin(filter_partners)
            ]

        if not df_ship.empty:
            # --- 요약 ---
            total_jobs = len(df_ship)
            total_qty = df_ship['stock'].sum()
            total_cost = df_ship['shipping_cost'].sum() if 'shipping_cost' in df_ship.columns else 0
            
            m1, m2, m3 = st.columns(3)
            m1.metric("총 출고건수", f"{total_jobs:,} 건")
            m2.metric("총 출고수량", f"{total_qty:,} 장")
            m3.metric("총 운임비", f"{total_cost:,} 원")
            st.divider()

            df_ship['group_key'] = df_ship.apply(lambda x: get_group_key(x, 'shipping_date'), axis=1)
            group_label = stat_type.replace('별', '')
            
            # 1. 상단: 배송업체별 통계 및 선택
            st.write("**배송업체별 운임비**")
            carrier_stats = df_ship.groupby('shipping_carrier').agg(출고건수=('id', 'count'), 총수량=('stock', 'sum'), 총운임비=('shipping_cost', 'sum')).sort_values('총운임비', ascending=False).reset_index()

            carrier_stats['선택'] = False
            edited_carrier_stats = st.data_editor(
                carrier_stats,
                column_order=["선택", "shipping_carrier", "총운임비", "총수량", "출고건수"],
                column_config={"선택": st.column_config.CheckboxColumn(default=False)},
                disabled=['shipping_carrier', '총운임비', '총수량', '출고건수'],
                width="stretch", hide_index=True, key="shipping_carrier_selector"
            )
            selected_carriers = edited_carrier_stats[edited_carrier_stats['선택']]['shipping_carrier'].tolist()
            show_actions(carrier_stats.drop(columns=['선택']), "배송업체별_운임통계", "배송업체별 운임비 통계", chart_col='총운임비')

            # [NEW] 비교 모드 토글
            compare_mode = st.toggle("업체별 비교", key="shipping_compare")

            st.divider()

            # 2. 데이터 필터링
            if selected_carriers:
                df_chart = df_ship[df_ship['shipping_carrier'].isin(selected_carriers)].copy()
            else:
                df_chart = df_ship.copy()

            # 3. 하단: 시계열 차트
            st.write(f"**{group_label}별 운임비 지출 추이**")
            
            if compare_mode and selected_carriers:
                group_cols = ['group_key', 'shipping_carrier']
                chart_color_col = alt.Color('shipping_carrier:N', title="배송업체")
            else:
                group_cols = ['group_key']
                chart_color_col = alt.value('#4c78a8')

            time_stats = df_chart.groupby(group_cols).agg(총운임비=('shipping_cost', 'sum')).reset_index().rename(columns={'group_key': group_label})

            base = alt.Chart(time_stats).encode(x=alt.X(f'{group_label}:N', axis=alt.Axis(labelAngle=-45), sort=None), y='총운임비:Q', color=chart_color_col, tooltip=[alt.Tooltip(f'{group_label}:N', title=group_label), alt.Tooltip('shipping_carrier:N', title='배송업체') if compare_mode else alt.Tooltip(), alt.Tooltip('총운임비:Q', title='총운임비', format=',')])
            if chart_type_opt == "막대형":
                chart = base.mark_bar(opacity=0.8).encode(xOffset='shipping_carrier:N' if compare_mode else alt.XOffset())
            else:
                chart = base.mark_line(point=alt.OverlayMarkDef(size=100, filled=True))

            st.dataframe(time_stats, width="stretch", hide_index=True)
            with st.expander("📈 그래프 보기", expanded=True):
                st.altair_chart(chart, use_container_width=True)
            show_actions(time_stats, f"운임비추이_{group_label}", f"{group_label}별 운임비 지출 추이", chart_col='총운임비')
            
            st.divider()
            st.write("📋 거래처별 출고 실적")
            # [수정] 출고방법(shipping_method) 컬럼 추가
            cust_stats = df_chart.groupby(['customer', 'shipping_method']).agg(출고건수=('id', 'count'), 총수량=('stock', 'sum'), 총운임비=('shipping_cost', 'sum')).sort_values('총수량', ascending=False).reset_index()
            st.dataframe(cust_stats, width="stretch", hide_index=True)
            show_actions(cust_stats, "거래처별_출고실적", "거래처별 출고 실적")
        else:
            st.info("조회된 데이터가 없습니다.")