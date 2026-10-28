import streamlit as st
import sqlite3
import re
import warnings
import datetime
import plotly.graph_objects as go
import plotly.express as px
import random

import yfinance as yf
import pandas as pd
import numpy as np
import bcrypt
import os
from openai import OpenAI

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

st.set_page_config(
    page_title="StockEd — Virtual Investment Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- MODERN FINTECH UI STYLING & CUSTOM CSS ---
def load_custom_css():
    st.markdown("""
    <style>
        /* Main font */
        .stApp {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }
        
        /* Theme-adaptive metric cards (looks great in both Light and Dark mode) */
        div[data-testid="stMetric"] {
            background-color: rgba(128, 128, 128, 0.05) !important;
            border: 1px solid rgba(128, 128, 128, 0.2) !important;
            padding: 16px !important;
            border-radius: 12px !important;
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            transition: all 0.3s ease;
        }
        
        div[data-testid="stMetric"]:hover {
            border-color: rgba(128, 128, 128, 0.4) !important;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }

        /* Allow Streamlit to handle text colors dynamically based on light/dark mode */
        div[data-testid="stMetric"] label {
            font-weight: 600 !important;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            font-weight: 800 !important;
        }

        /* Sleek header styling */
        h1, h2, h3 {
            font-weight: 700;
            letter-spacing: -0.025em;
        }

        /* Custom styling for tabs */
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px 8px 0px 0px;
            padding: 10px 20px;
            font-weight: 600;
        }
    </style>
    """, unsafe_allow_html=True)

load_custom_css()

# Initialize the OpenAI client pointing to NVIDIA NIM
client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = "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"
)

def get_nemotron_stock_advice(stock_symbol, user_action, portfolio_context):
    prompt = f"""
    You are an expert financial mentor for a virtual stock market learning app. 
    A user is about to {user_action} stock '{stock_symbol}'. 
    Their current portfolio context is: {portfolio_context}.
    Provide a concise, engaging, and realistic risk evaluation and learning tip for a beginner. Keep it under 4 sentences.
    """
    
    try:
        response = client.chat.completions.create(
            model="nvidia/nemotron-3-nano-30b-a3b", # Or your preferred Nemotron model from the catalog
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Advisor is temporarily offline: {str(e)}"

DB_PATH = "users.db"
FD_ANNUAL_RATE = 0.065
FD_EARLY_RATE = 0.055


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------
def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                wallet_balance REAL NOT NULL DEFAULT 10000.0,
                investment_strategy TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                sub_asset TEXT,
                ticker TEXT,
                units REAL NOT NULL DEFAULT 0,
                invested_amount REAL NOT NULL DEFAULT 0,
                average_price REAL NOT NULL DEFAULT 0,
                created_date TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_holding 
            ON holdings (
                username, 
                asset_class, 
                COALESCE(sub_asset, ''), 
                COALESCE(ticker, '')
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS fixed_deposits (
                fd_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                principal REAL NOT NULL,
                annual_rate REAL NOT NULL,
                tenure_months INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                maturity_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                sub_asset TEXT,
                ticker TEXT,
                transaction_type TEXT NOT NULL,
                units REAL NOT NULL DEFAULT 0,
                amount REAL NOT NULL,
                price REAL NOT NULL DEFAULT 0,
                tenure_months INTEGER,
                created_date TEXT NOT NULL
            )
        """)

# Initialize database on startup
init_db()

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
def is_valid_email(email):
    return bool(re.fullmatch(r"^[\w\.\-+]+@[\w\-]+\.[A-Za-z]{2,}$", email))


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def register_user(username, email, password):
    with get_connection() as conn:
        try:
            conn.execute(
                """INSERT INTO users
                    (username, email, password_hash)
                    VALUES (?, ?, ?)""",
                (username, email, hash_password(password)),
            )
            return True, f"Account created for {username}. Starting capital: $10,000."
        except sqlite3.IntegrityError:
            return False, "Username or email already exists."


def authenticate_user(username, password):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT username, email, wallet_balance,
                     investment_strategy, password_hash
               FROM users WHERE username = ?""",
            (username,),
        ).fetchone()

    if not row:
        return None

    stored_hash = row[4]
    if not verify_password(password, stored_hash):
        return None

    return {
        "username": row[0],
        "email": row[1],
        "wallet_balance": row[2],
        "investment_strategy": row[3],
    }


def update_wallet(username, balance):
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET wallet_balance = ? WHERE username = ?",
            (balance, username),
        )


def update_strategy(username, strategy):
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET investment_strategy = ? WHERE username = ?",
            (strategy, username),
        )


def get_holdings(username):
    with get_connection() as conn:
        return conn.execute(
            """SELECT holding_id, asset_class, sub_asset, ticker, units,
                     invested_amount, average_price, created_date
               FROM holdings WHERE username = ?""",
            (username,),
        ).fetchall()


def get_fixed_deposits(username, active_only=True):
    query = """SELECT fd_id, principal, annual_rate, tenure_months,
                    start_date, maturity_date, status
             FROM fixed_deposits WHERE username = ?"""
    params = [username]

    if active_only:
        query += " AND status = 'ACTIVE'"

    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def add_transaction(username, asset_class, sub_asset, ticker,
                    transaction_type, units, amount, price, tenure_months=None):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO transactions
               (username, asset_class, sub_asset, ticker, transaction_type,
                units, amount, price, tenure_months, created_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                username, asset_class, sub_asset, ticker, transaction_type,
                units, amount, price, tenure_months,
                datetime.date.today().isoformat(),
            ),
        )


def buy_asset(username, asset_class, sub_asset, ticker, units, price):
    cost = units * price

    with get_connection() as conn:
        row = conn.execute(
            """SELECT holding_id, units, invested_amount
               FROM holdings
               WHERE username = ? AND asset_class = ?
                 AND IFNULL(sub_asset, '') = IFNULL(?, '')
                 AND IFNULL(ticker, '') = IFNULL(?, '')""",
            (username, asset_class, sub_asset, ticker),
        ).fetchone()

        if row:
            holding_id, old_units, old_invested = row
            new_units = old_units + units
            new_invested = old_invested + cost
            avg_price = new_invested / new_units if new_units > 0 else price

            conn.execute(
                """UPDATE holdings
                   SET units = ?, invested_amount = ?, average_price = ?
                   WHERE holding_id = ?""",
                (new_units, new_invested, avg_price, holding_id),
            )
        else:
            conn.execute(
                """INSERT INTO holdings
                   (username, asset_class, sub_asset, ticker, units,
                    invested_amount, average_price, created_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    username, asset_class, sub_asset, ticker,
                    units, cost, price,
                    datetime.date.today().isoformat(),
                ),
            )

    add_transaction(
        username, asset_class, sub_asset, ticker,
        "BUY", units, cost, price,
    )

    return cost


def sell_asset(username, asset_class, sub_asset, ticker, units_to_sell, current_price):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT holding_id, units, invested_amount, average_price
               FROM holdings
               WHERE username = ? AND asset_class = ?
                 AND IFNULL(sub_asset, '') = IFNULL(?, '')
                 AND IFNULL(ticker, '') = IFNULL(?, '')""",
            (username, asset_class, sub_asset, ticker),
        ).fetchone()

        if not row:
            return False, "Holding not found. You do not own this asset.", 0.0

        holding_id, current_units, invested_amount, avg_price = row

        if units_to_sell > current_units + 1e-6:
            return False, f"Cannot sell {units_to_sell:.2f} units. You only own {current_units:.2f}.", 0.0

        proceeds = units_to_sell * current_price
        new_units = max(0.0, current_units - units_to_sell)

        if new_units <= 1e-6:
            conn.execute("DELETE FROM holdings WHERE holding_id = ?", (holding_id,))
        else:
            new_invested = invested_amount * (new_units / current_units)
            conn.execute(
                """UPDATE holdings
                   SET units = ?, invested_amount = ?
                   WHERE holding_id = ?""",
                (new_units, new_invested, holding_id),
            )

    add_transaction(
        username, asset_class, sub_asset, ticker,
        "SELL", units_to_sell, proceeds, current_price,
    )

    return True, f"Successfully sold {units_to_sell:.2f} units for ${proceeds:,.2f}.", proceeds


def create_fd(username, principal, tenure_months):
    start = datetime.date.today()
    maturity = start + datetime.timedelta(days=int(tenure_months * 30.4375))

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO fixed_deposits
               (username, principal, annual_rate, tenure_months,
                start_date, maturity_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, principal, FD_ANNUAL_RATE, tenure_months,
             start.isoformat(), maturity.isoformat()),
        )

    add_transaction(
        username, "FD (Fixed Deposits)", None, None,
        "FD_CREATE", 0, principal, 1.0, tenure_months,
    )

    return maturity


def close_fd(username, fd_id):
    with get_connection() as conn:
        fd = conn.execute(
            """SELECT fd_id, principal, annual_rate, tenure_months,
                     start_date, maturity_date
               FROM fixed_deposits
               WHERE fd_id = ? AND username = ? AND status = 'ACTIVE'""",
            (fd_id, username),
        ).fetchone()

        if not fd:
            return None

        fd_id, principal, rate, tenure, start_date, maturity_date = fd
        start = datetime.date.fromisoformat(start_date)
        maturity = datetime.date.fromisoformat(maturity_date)
        today = datetime.date.today()

        matured = today >= maturity
        used_rate = rate if matured else FD_EARLY_RATE
        days = max((today - start).days, 0)

        value = principal * ((1 + used_rate / 365) ** days)
        interest = value - principal

        conn.execute(
            "UPDATE fixed_deposits SET status = 'CLOSED' WHERE fd_id = ?",
            (fd_id,),
        )

    add_transaction(
        username, "FD (Fixed Deposits)", None, None,
        "FD_CLOSE", 0, value, 1.0, tenure,
    )

    return value, interest, not matured


# ---------------------------------------------------------
# MARKET DATA & COMPANY MAPPING
# ---------------------------------------------------------
COMMODITY_TICKERS = {
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Platinum": "PL=F",
    "Crude Oil": "CL=F",
}

COMPANY_TICKER_MAP = {
    "APPLE": "AAPL",
    "MICROSOFT": "MSFT",
    "NVIDIA": "NVDA",
    "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL",
    "AMAZON": "AMZN",
    "TESLA": "TSLA",
    "NETFLIX": "NFLX",
    "META": "META",
    "FACEBOOK": "META",
    "COCA COLA": "KO",
    "WALMART": "WMT"
}

def resolve_company_to_ticker(user_input):
    cleaned = user_input.strip().upper()
    return COMPANY_TICKER_MAP.get(cleaned, cleaned)


@st.cache_data(ttl=300, show_spinner=False)
def get_latest_price(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_history(ticker, period="10y"):
    try:
        return yf.Ticker(ticker).history(period=period)
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_data" not in st.session_state:
    st.session_state.user_data = None


# ---------------------------------------------------------
# LOGIN / REGISTER
# ---------------------------------------------------------
if not st.session_state.logged_in:
    menu = st.sidebar.radio("Navigation", ["Log In", "Register Account"])

    if menu == "Log In":
        st.title("🔐 Log In to StockEd")

        with st.form("login_form"):
            username = st.text_input("Username").strip()
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log In")

        if submitted:
            if not username or not password:
                st.error("Please fill in all fields.")
            else:
                user = authenticate_user(username, password)

                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_data = user
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

    else:
        st.title("📱 Create Account")

        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("Username").strip()
            email = st.text_input("Email").strip()
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Sign Up")

        if submitted:
            if not all([username, email, password, confirm]):
                st.error("Please fill in all fields.")
            elif not is_valid_email(email):
                st.error("Enter a valid email.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                success, message = register_user(username, email, password)

                if success:
                    st.success(message)
                else:
                    st.error(message)


# ---------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------
else:
    user = st.session_state.user_data

    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Profile & Settings")
    st.sidebar.write(f"**Logged in as:** {user['username']}")

    ALL_OPTIONS = [
        "Fixed Income (FD and Bonds)",
        "Shares",
        "Metals & Oil",
        "Real Estate",
    ]

    if user["investment_strategy"]:
        with st.sidebar.expander("✏️ Edit Passive Income Options"):
            current_options = [x.strip() for x in user["investment_strategy"].split(",")]

            updated_selected = []
            for option in ALL_OPTIONS:
                is_checked = st.checkbox(
                    option,
                    value=(option in current_options),
                    key=f"sidebar_opt_{option}"
                )
                if is_checked:
                    updated_selected.append(option)

            if st.button("Update Options"):
                if not updated_selected:
                    st.sidebar.error("Select at least one option.")
                else:
                    new_strategy = ", ".join(updated_selected)
                    update_strategy(user["username"], new_strategy)
                    user["investment_strategy"] = new_strategy
                    st.session_state.user_data["investment_strategy"] = new_strategy
                    st.sidebar.success("Options updated!")
                    st.rerun()

    if st.sidebar.button("Log Out"):
        st.session_state.logged_in = False
        st.session_state.user_data = None
        st.rerun()

    if not user["investment_strategy"]:
        st.title("🎯 Choose Your Passive Income Options")

        selected = []

        for option in ALL_OPTIONS:
            if st.checkbox(option, key=f"init_opt_{option}"):
                selected.append(option)

        if st.button("Confirm Selection"):
            if not selected:
                st.error("Select at least one option.")
            else:
                strategy = ", ".join(selected)
                update_strategy(user["username"], strategy)
                user["investment_strategy"] = strategy
                st.session_state.user_data["investment_strategy"] = strategy
                st.rerun()

    else:
        selected_assets = [
            x.strip() for x in user["investment_strategy"].split(",")
        ] if user["investment_strategy"] else []

        st.title(f"📈 Dashboard — {user['username']}")
        st.info(f"**Your selected passive-income options:** {user['investment_strategy']}")

        holdings = get_holdings(user["username"])
        fds = get_fixed_deposits(user["username"])

        total_invested = sum(fd[1] for fd in fds)
        total_current = sum(
            fd[1] * ((1 + fd[2] / 365) ** max(
                (datetime.date.today() - datetime.date.fromisoformat(fd[4])).days, 0
            ))
            for fd in fds
        )

        for h in holdings:
            _, asset_class, sub_asset, ticker, units, invested, avg_price, _ = h

            if asset_class in ["Shares", "Real Estate"]:
                ticker = ticker or ("NVDA" if asset_class == "Shares" else "O")
                price = get_latest_price(ticker) or avg_price
                current = units * price
            elif asset_class == "Metals & Oil":
                ticker = ticker or COMMODITY_TICKERS.get(sub_asset, "GC=F")
                price = get_latest_price(ticker) or avg_price
                current = units * price
            else:
                current = invested

            total_invested += invested
            total_current += current

        profit = total_current - total_invested
        net_worth = user["wallet_balance"] + total_current

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("💵 Available Wallet", f"${user['wallet_balance']:,.2f}", delta="Liquid Cash")

        with col2:
            st.metric("📊 Total Invested", f"${total_invested:,.2f}", delta="Active Capital")

        with col3:
            st.metric("📈 Net Profit / Loss", f"${profit:,.2f}", delta=f"{'+' if profit >= 0 else ''}${profit:,.2f}")

        with col4:
            st.metric("💎 Portfolio Net Worth", f"${net_worth:,.2f}", delta="Total Assets")

        st.markdown("---")

        tabs = st.tabs(["📋 Portfolio"] + selected_assets + ["🤖 AI Advisor"])

        # ---------------- Portfolio ----------------
# ---------------- Portfolio ----------------
        # ---------------- Portfolio ----------------
        # ---------------- Portfolio ----------------
        with tabs[0]:
            st.subheader("Your Portfolio")

            # --- 1. PROFIT-BASED INVESTOR STATUS & MILESTONE TRACKER ---
            total_profit_loss = 0.0
            
            # Calculate profit from active FDs
            for fd in fds:
                fd_id, principal, rate, tenure, start_date, maturity_date, status = fd
                val = principal * ((1 + rate / 365) ** max(
                    (datetime.date.today() - datetime.date.fromisoformat(start_date)).days, 0
                ))
                total_profit_loss += (val - principal)

            # Calculate profit from holdings (Shares, Real Estate, Commodities, Bonds, ETFs)
            for h in holdings:
                _, asset_class, sub_asset, ticker, units, invested, avg_price, _ = h
                if asset_class in ["Shares", "Real Estate", "Dividend ETFs & Index Funds"]:
                    ticker = ticker or ("NVDA" if asset_class == "Shares" else "O")
                    price = get_latest_price(ticker) or avg_price
                    current_val = units * price
                    total_profit_loss += (current_val - invested)
                elif asset_class == "Metals & Oil":
                    ticker = ticker or COMMODITY_TICKERS.get(sub_asset, "GC=F")
                    price = get_latest_price(ticker) or avg_price
                    current_val = units * price
                    total_profit_loss += (current_val - invested)
                elif asset_class == "Fixed Income (FDs & Bonds)":
                    total_profit_loss += (invested * 0.04)

            # Determine Investor Tier based on Net Profit ($)
            if total_profit_loss >= 2000:
                investor_tier = "💎 Master Portfolio Tycoon ($2,000+ Profit)"
                progress_val = 100
            elif total_profit_loss >= 1000:
                investor_tier = "🥇 Expert Wealth Builder ($1,000+ Profit)"
                progress_val = 75
            elif total_profit_loss >= 250:
                investor_tier = "🥈 Smart Trader ($250+ Profit)"
                progress_val = 50
            elif total_profit_loss > 0:
                investor_tier = "🥉 Positive Growth ($0+ Profit)"
                progress_val = 35
            else:
                investor_tier = "🌱 Beginner Learner (Market Learning Phase)"
                progress_val = 15

            # Display motivational card at top of portfolio
            col_p1, col_p2 = st.columns([2, 1])
            with col_p1:
                st.markdown(f"**Current Investor Status:** {investor_tier}")
                st.progress(progress_val, text=f"Performance Milestone Progress: {progress_val}%")
            with col_p2:
                st.metric("Total Net Profit / Loss", f"${total_profit_loss:,.2f}", delta=f"{'+' if total_profit_loss >= 0 else ''}${total_profit_loss:,.2f}")

            st.markdown("---")

            # --- 2. ASSET ALLOCATION BREAKDOWN PIE CHART ---
            st.markdown("### 📊 Portfolio Asset Allocation")
            
            allocation_dict = {
                "Fixed Income (FDs & Bonds)": sum(fd[1] for fd in fds),
                "Shares": 0.0,
                "Real Estate": 0.0,
                "Metals & Oil": 0.0,
                "Dividend ETFs & Index Funds": 0.0
            }

            for h in holdings:
                _, asset_class, sub_asset, ticker, units, invested, avg_price, _ = h
                if asset_class in allocation_dict:
                    allocation_dict[asset_class] += invested
                else:
                    allocation_dict[asset_class] = invested

            active_allocations = {k: v for k, v in allocation_dict.items() if v > 0}

            if active_allocations:
                df_alloc = pd.DataFrame(list(active_allocations.items()), columns=["Asset Class", "Invested Amount"])
                
                fig_pie = px.pie(
                    df_alloc, 
                    names="Asset Class", 
                    values="Invested Amount", 
                    hole=0.4,
                    title="Capital Distribution by Asset Class"
                )
                fig_pie.update_layout(margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Make your first investment in the marketplace tabs to view your asset allocation breakdown chart!")

            st.markdown("---")

            # --- 3. DETAILED HOLDINGS & ASSETS TABLE (Including FDs & Bonds) ---
            st.markdown("### Active Holdings & Assets")
            if not holdings and not fds:
                st.info("Your portfolio is currently empty! Head over to the asset marketplaces to make your first trade.")
            else:
                rows = []
                
                # Include Active Fixed Deposits in the table
                for fd in fds:
                    fd_id, principal, rate, tenure, start_date, maturity_date, status = fd
                    val = principal * ((1 + rate / 365) ** max(
                        (datetime.date.today() - datetime.date.fromisoformat(start_date)).days, 0
                    ))
                    rows.append({
                        "Asset Class": "Fixed Income (Bank FD)",
                        "Name / Ticker": f"FD #{fd_id} ({tenure}M @ {rate*100:.1f}%)",
                        "Units / Shares": 1.0,
                        "Invested ($)": f"${principal:,.2f}",
                        "Current Value ($)": f"${val:,.2f}"
                    })

                # Include Holdings & Treasury Bonds in the table
                for h in holdings:
                    _, asset_class, sub_asset, ticker, units, invested, avg_price, _ = h
                    if asset_class in ["Shares", "Real Estate", "Dividend ETFs & Index Funds"]:
                        ticker = ticker or ("NVDA" if asset_class == "Shares" else "O")
                        price = get_latest_price(ticker) or avg_price
                        current_val = units * price
                    elif asset_class == "Metals & Oil":
                        ticker = ticker or COMMODITY_TICKERS.get(sub_asset, "GC=F")
                        price = get_latest_price(ticker) or avg_price
                        current_val = units * price
                    else:  # Treasury Bonds / Fixed Income holdings
                        current_val = invested

                    rows.append({
                        "Asset Class": asset_class,
                        "Name / Ticker": sub_asset or ticker,
                        "Units / Shares": units,
                        "Invested ($)": f"${invested:,.2f}",
                        "Current Value ($)": f"${current_val:,.2f}"
                    })

                if rows:
                    st.dataframe(rows, use_container_width=True)

        # ---------------- Selected asset tabs ----------------
        for tab_index, asset in enumerate(selected_assets, start=1):
            with tabs[tab_index]:
                st.subheader(f"{asset}")

                if asset == "Fixed Income (FD and Bonds)":
                    st.markdown("### 🏦 Fixed Income Marketplace: FDs & Government Bonds")
                    st.caption("Build stable, low-risk passive income using guaranteed bank fixed deposits or government-backed sovereign bonds.")

                    income_type = st.radio("Choose Fixed Income Asset", ["Fixed Deposit (FD)", "Government Treasury Bond"], horizontal=True)

                    if income_type == "Fixed Deposit (FD)":
                        st.markdown("#### 🏛️ Traditional Bank Fixed Deposit")
                        st.info(
                            "- Interest rate: **6.5% per year** (Guaranteed at maturity)\n"
                            "- Early withdrawal rate: **5.5% per year**\n"
                            "- Choose a lock-in period below"
                        )

                        with st.form("fd_form"):
                            amount = st.number_input(
                                "FD amount ($)",
                                min_value=100.0,
                                max_value=100000.0,
                                value=1000.0,
                                step=100.0,
                            )
                            tenure = st.selectbox(
                                "Tenure",
                                [6, 12, 24, 36, 60],
                                format_func=lambda x: f"{x} months",
                            )
                            create = st.form_submit_button("Create FD")

                        if create:
                            if user["wallet_balance"] < amount:
                                st.error("Insufficient wallet balance.")
                            else:
                                maturity = create_fd(user["username"], amount, tenure)
                                user["wallet_balance"] -= amount
                                update_wallet(user["username"], user["wallet_balance"])
                                st.success(f"FD created. Matures on {maturity}.")
                                st.rerun()

                        st.markdown("### Close FD")
                        active_fds = get_fixed_deposits(user["username"])

                        if not active_fds:
                            st.info("No active FDs.")
                        else:
                            fd_map = {
                                fd[0]: f"FD #{fd[0]} — ${fd[1]:,.2f} — matures {fd[5]}"
                                for fd in active_fds
                            }

                            chosen_fd = st.selectbox(
                                "Select FD",
                                list(fd_map.keys()),
                                format_func=lambda x: fd_map[x],
                            )

                            if st.button("Close Selected FD"):
                                result = close_fd(user["username"], chosen_fd)

                                if result:
                                    value, interest, early = result
                                    user["wallet_balance"] += value
                                    update_wallet(user["username"], user["wallet_balance"])

                                    if early:
                                        st.warning(
                                            f"Early withdrawal: received ${value:,.2f}. "
                                            f"Interest earned: ${interest:,.2f}."
                                        )
                                    else:
                                        st.success(
                                            f"FD matured: received ${value:,.2f}. "
                                            f"Interest earned: ${interest:,.2f}."
                                        )

                                    st.rerun()

                    else:
                        st.markdown("#### 📜 Sovereign Government Treasury Bonds")
                        st.info(
                            "- **10-Year U.S. Treasury Note Proxy (^TNX)**\n"
                            "- Backed by government credit; ultra-low risk.\n"
                            "- Earns steady periodic coupon yields."
                        )

                        # Using live 10-year treasury yield ticker from Yahoo Finance (^TNX represents 10-year yield %)
                        bond_ticker = "^TNX"
                        bond_yield_raw = get_latest_price(bond_ticker)
                        annual_bond_rate = (bond_yield_raw / 100.0) if bond_yield_raw else 0.0425

                        st.metric("Current 10-Year Treasury Yield Benchmark", f"{annual_bond_rate * 100:.2f}% per year")

                        with st.form("bond_form"):
                            bond_investment = st.number_input(
                                "Bond Investment Amount ($)",
                                min_value=100.0,
                                max_value=100000.0,
                                value=1000.0,
                                step=100.0,
                            )
                            bond_tenure_years = st.selectbox("Bond Maturity Term", [1, 3, 5, 10], format_func=lambda x: f"{x} Years")
                            buy_bond_submit = st.form_submit_button("Purchase Treasury Bonds")

                        if buy_bond_submit:
                            if user["wallet_balance"] < bond_investment:
                                st.error("Insufficient wallet balance.")
                            else:
                                # Record bond as fixed-income asset holding using buy_asset helper
                                buy_asset(
                                    user["username"], "Fixed Income (FDs & Bonds)",
                                    f"US Treasury Bond ({bond_tenure_years}Y)", bond_ticker, bond_investment, 1.0
                                )
                                user["wallet_balance"] -= bond_investment
                                update_wallet(user["username"], user["wallet_balance"])
                                st.success(f"Successfully purchased ${bond_investment:,.2f} in Government Treasury Bonds yielding {annual_bond_rate * 100:.2f}%!")
                                st.rerun()

                        # --- NEW: DISPLAY ACTIVE TREASURY BONDS & LIQUIDATION OPTION ---
                        st.markdown("---")
                        st.markdown("### Your Active Treasury Bonds")
                        
                        holdings = get_holdings(user["username"])
                        active_bonds = [h for h in holdings if h[1] == "Fixed Income (FDs & Bonds)"]

                        if not active_bonds:
                            st.info("No active Treasury Bonds owned.")
                        else:
                            bond_map = {
                                h[0]: f"{h[2]} — Invested: ${h[5]:,.2f}"
                                for h in active_bonds
                            }

                            chosen_bond_id = st.selectbox(
                                "Select Treasury Bond Holding",
                                list(bond_map.keys()),
                                format_func=lambda x: bond_map[x],
                                key="select_bond_to_sell"
                            )

                            if st.button("Liquidate Selected Bond"):
                                selected_holding = next(h for h in active_bonds if h[0] == chosen_bond_id)
                                holding_id, _, sub_asset, ticker, units, invested_amt, avg_price, _ = selected_holding
                                
                                success, msg, proceeds = sell_asset(
                                    user["username"], "Fixed Income (FDs & Bonds)", sub_asset, ticker, units, avg_price
                                )
                                if success:
                                    user["wallet_balance"] += proceeds
                                    update_wallet(user["username"], user["wallet_balance"])
                                    st.success(f"Successfully liquidated bond and recovered ${proceeds:,.2f} to your wallet.")
                                    st.rerun()
                                else:
                                    st.error(msg)

                elif asset == "Shares":
                    st.markdown("### 📈 Shares Marketplace & Real-World Investment Analysis")
                    st.caption("Learn real-world investing with live market data, fundamental metrics, and AI-driven risk evaluation.")

                    # --- 1. GOOGLE-LIKE COMPANY SEARCH ENGINE ---
                    search_query = st.text_input(
                        "🔍 Search Company Name or Ticker (e.g., 'Apple', 'Microsoft', 'TSLA'):",
                        value="Apple",
                        key="company_search_input"
                    )

                    ticker = None
                    selected_company_label = None

                    if search_query.strip():
                        try:
                            search_results = yf.Search(search_query, max_results=6, enable_fuzzy_query=True).quotes
                            
                            if search_results:
                                options = {
                                    f"{res.get('longname') or res.get('shortname') or res['symbol']} ({res['symbol']})": res['symbol']
                                    for res in search_results if 'symbol' in res
                                }
                                
                                selected_company_label = st.selectbox(
                                    "Matching Companies Found (Select one):",
                                    options=list(options.keys()),
                                    key="company_select_box"
                                )
                                
                                ticker = options[selected_company_label]
                            else:
                                st.warning(f"No company found for '{search_query}'. Try typing the exact ticker symbol.")
                                ticker = search_query.strip().upper()
                        except Exception as e:
                            ticker = search_query.strip().upper()

                    # --- 2. FETCH DATA FOR THE SELECTED TICKER ---
                    if ticker:
                        try:
                            stock = yf.Ticker(ticker)
                            hist_data = stock.history(period="10y")
                            info = stock.info
                            
                            price = info.get("currentPrice") or info.get("regularMarketPrice")
                            if not price and not hist_data.empty:
                                price = hist_data['Close'].iloc[-1]

                            if not price:
                                st.error("Could not fetch price for the selected stock. Try selecting another company.")
                            else:
                                company_title = info.get('longName', ticker)
                                st.markdown(f"#### 📊 {company_title} ({ticker}) Overview")
                                
                                # Real-World Financial Metrics
                                pe_ratio = info.get("trailingPE", "N/A")
                                div_yield = info.get("dividendYield", 0)
                                div_yield_pct = f"{div_yield * 100:.2f}%" if div_yield else "None / 0%"
                                market_cap = info.get("marketCap", "N/A")
                                
                                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                                col_m1.metric("Current Price", f"${price:,.2f}")
                                col_m2.metric("P/E Ratio", f"{pe_ratio}" if isinstance(pe_ratio, str) else f"{pe_ratio:.2f}")
                                col_m3.metric("Dividend Yield", div_yield_pct)
                                col_m4.metric("Market Cap", f"${market_cap:,}" if isinstance(market_cap, (int, float)) else market_cap)

                                # --- 3. 10-YEAR PLOTLY PRICE CHART ---
                                st.markdown("#### 📉 10-Year Price History Trend")
                                if not hist_data.empty and "Close" in hist_data.columns:
                                    fig = px.line(
                                        hist_data,
                                        x=hist_data.index,
                                        y="Close",
                                        title=f"{company_title} - 10 Year Price Chart",
                                        labels={"Close": "Price (USD)", "index": "Year"}
                                    )
                                    fig.update_traces(line_color="#00CC96", line_width=2)
                                    fig.update_layout(
                                        xaxis_title="Year",
                                        yaxis_title="Price ($)",
                                        hovermode="x unified",
                                        margin=dict(l=20, r=20, t=40, b=20)
                                    )
                                    st.plotly_chart(fig, use_container_width=True)
                                else:
                                    st.warning("Historical price graph is currently unavailable for this stock.")

                                # --- 4. NVIDIA AI REAL-WORLD INVESTMENT & RISK ANALYZER ---
                                # --- 4. NVIDIA AI VISUAL INVESTMENT & RISK DASHBOARD ---
                                # --- 4. NVIDIA AI VISUAL CHARTS & METRICS DASHBOARD ---
                                st.markdown("---")
                                st.markdown("#### 🧠 NVIDIA AI Investment Intelligence & Risk Metrics")
                                st.caption("Powered by NVIDIA Nemotron to convert deep market fundamentals into visual gauges and metrics.")

                                if st.button("Generate AI Visual Assessment", key="nvidia_market_assessment"):
                                    with st.spinner("NVIDIA GPU-accelerated model computing valuation scores and risk metrics..."):
                                        try:
                                            analysis_prompt = f"""
                                            Evaluate this stock for a beginner learning safe investing and passive income:
                                            - Company: {company_title} ({ticker})
                                            - Current Price: ${price:,.2f}
                                            - P/E Ratio: {pe_ratio}
                                            - Dividend Yield: {div_yield_pct}
                                            - Summary: {info.get('longBusinessSummary', 'N/A')[:300]}

                                            Provide a brief assessment divided strictly into 3 short bullet points:
                                            1. VALUATION: (Is it overpriced or fair?)
                                            2. PASSIVE_INCOME: (Is dividend growth reliable?)
                                            3. RISK_WARNING: (What is the main danger?)
                                            """
                                            
                                            completion = client.chat.completions.create(
                                                model="nvidia/nemotron-3.5-lightning-30b-a3b",
                                                messages=[
                                                    {"role": "system", "content": "You are a concise financial mentor. Format your answers clearly."},
                                                    {"role": "user", "content": analysis_prompt}
                                                ],
                                                temperature=0.3,
                                                max_tokens=600,
                                                extra_body={"chat_template_kwargs": {"enable_thinking": False}}
                                            )
                                            
                                            ai_text = completion.choices[0].message.content
                                            
                                            st.success("✅ NVIDIA AI Intelligence Metrics Generated!")

                                            # --- VISUAL METRICS & PROBABILITY BARS ---
                                            col_c1, col_c2, col_c3 = st.columns(3)
                                            
                                            with col_c1:
                                                st.metric(label="📊 Valuation Health", value="Moderate Risk", delta="P/E Evaluated")
                                                # Visual progress bar simulating a safety/valuation score
                                                st.progress(65, text="Safety Score: 65 / 100")

                                            with col_c2:
                                                st.metric(label="💵 Passive Income Index", value=div_yield_pct, delta="Yield Status")
                                                st.progress(40 if div_yield == 0 else 80, text="Yield Reliability")

                                            with col_c3:
                                                st.metric(label="⚠️ Volatility Index", value="Medium", delta="Market Adjusted")
                                                st.progress(50, text="Risk Level")

                                            # --- MINI BAR CHART FOR FINANCIAL COMPARISON ---
                                            st.markdown("##### 📈 Quick Financial Overview Chart")
                                            # Creating a clean visual bar chart using pandas & plotly/streamlit for professional look
                                            chart_data = pd.DataFrame({
                                                "Metric": ["P/E Ratio", "Dividend Yield (%)", "Safety Score"],
                                                "Value": [
                                                    float(pe_ratio) if isinstance(pe_ratio, (int, float)) else 20.0,
                                                    (float(div_yield) * 100) if div_yield else 1.0,
                                                    65.0
                                                ]
                                            })
                                            st.bar_chart(chart_data.set_index("Metric"))

                                            # Detailed Breakdown Expander
                                            with st.expander("📄 View AI Expert Rationale & Breakdown"):
                                                st.write(ai_text)
                                                
                                        except Exception as e:
                                            st.error(f"Could not generate NVIDIA AI assessment: {e}")

                                # --- 5. BUY & SELL TRANSACTIONS ---
                                share_holding = next(
                                    (h for h in holdings if h[1] == "Shares" and h[3] == ticker), None
                                )
                                owned_shares = share_holding[4] if share_holding else 0.0
                                avg_buy_price = share_holding[6] if share_holding else 0.0

                                st.markdown("---")
                                col_s_buy, col_s_sell = st.columns(2)

                                with col_s_buy:
                                    st.markdown("#### Buy Shares")
                                    shares_buy = st.number_input(
                                        "Shares to buy",
                                        min_value=0.01,
                                        value=1.0,
                                        step=0.01,
                                        key="shares_buy_qty"
                                    )
                                    
                                    cost = shares_buy * price
                                    st.write(f"**Total Cost:** ${cost:,.2f}")

                                    if st.button("Buy Shares", key="confirm_buy_shares"):
                                        if user["wallet_balance"] < cost:
                                            st.error("Insufficient wallet balance.")
                                        else:
                                            buy_asset(
                                                user["username"], "Shares", None,
                                                ticker, shares_buy, price,
                                            )
                                            user["wallet_balance"] -= cost
                                            update_wallet(user["username"], user["wallet_balance"])
                                            st.success(f"Successfully bought {shares_buy:.2f} shares of {ticker}.")
                                            st.rerun()

                                with col_s_sell:
                                    st.markdown("#### Sell Shares")
                                    if owned_shares <= 0:
                                        st.info(f"You do not own any shares of {ticker} to sell.")
                                    else:
                                        shares_sell = st.number_input(
                                            f"Shares to sell (Owned: {owned_shares:.2f})",
                                            min_value=0.01,
                                            max_value=float(owned_shares),
                                            value=min(1.0, float(owned_shares)),
                                            step=0.01,
                                            key="shares_sell_qty"
                                        )
                                        
                                        proceeds = shares_sell * price
                                        cost_basis = shares_sell * avg_buy_price
                                        pnl = proceeds - cost_basis
                                        pnl_pct = (pnl / cost_basis) * 100 if cost_basis > 0 else 0

                                        st.write(f"🏷️ **Selling Price:** ${price:,.2f} / share")
                                        st.write(f"💵 **Proceeds:** ${proceeds:,.2f}")
                                        if pnl >= 0:
                                            st.success(f"📈 Profit: +${pnl:,.2f} (+{pnl_pct:.2f}%)")
                                        else:
                                            st.error(f"📉 Loss: -${abs(pnl):,.2f} ({pnl_pct:.2f}%)")

                                        if st.button("Confirm Sell Shares", key="confirm_sell_shares"):
                                            success, msg, rec_proceeds = sell_asset(
                                                user["username"], "Shares", None, ticker, shares_sell, price
                                            )
                                            if success:
                                                user["wallet_balance"] += rec_proceeds
                                                update_wallet(user["username"], user["wallet_balance"])
                                                st.success(msg)
                                                st.rerun()
                                            else:
                                                st.error(msg)

                        except Exception as e:
                            st.error(f"Error loading ticker data: {e}")

                elif asset == "Metals & Oil":
                    st.markdown("### 🪙 Commodities Marketplace: Precious Metals & Energy")
                    st.caption("Trade real-world commodities with live market feeds, flexible unit conversions, and visual performance tracking.")

                    commodity = st.selectbox(
                        "Choose commodity",
                        ["Gold", "Silver", "Platinum", "Crude Oil"],
                        key="commodity_select_box"
                    )

                    ticker = COMMODITY_TICKERS[commodity]
                    price = get_latest_price(ticker)

                    if not price:
                        st.error("Could not fetch current market price for this commodity.")
                    else:
                        # Define unit conversion options and factors
                        if commodity == "Crude Oil":
                            unit_options = ["Barrels (bbl)", "Liters (L)", "Gallons (gal)"]
                            conversion_factors = {
                                "Barrels (bbl)": 1.0,
                                "Gallons (gal)": 0.0238, # 1 barrel ~ 42 US gallons
                                "Liters (L)": 0.00629     # 1 barrel ~ 159 liters
                            }
                        else:
                            unit_options = ["Ounces (oz)", "Grams (g)", "Kilograms (kg)", "Pounds (lbs)"]
                            conversion_factors = {
                                "Ounces (oz)": 1.0,
                                "Grams (g)": 0.03215,    # 1 gram = 0.03215 troy oz
                                "Kilograms (kg)": 32.1507, # 1 kg = 32.15 troy oz
                                "Pounds (lbs)": 14.5833   # 1 lb = 14.58 troy oz
                            }

                        selected_unit = st.selectbox("Select Measurement Unit", unit_options, key="commodity_unit_select")
                        
                        factor = conversion_factors[selected_unit]
                        price_per_selected_unit = price * factor

                        # --- VISUAL METRICS DASHBOARD ---
                        st.markdown(f"#### 📊 {commodity} Live Market Overview")
                        col_m1, col_m2, col_m3 = st.columns(3)
                        
                        col_m1.metric(f"Price (per {selected_unit})", f"${price_per_selected_unit:,.2f}", delta="Live Feed")
                        col_m2.metric("Market Reference", ticker, delta="Exchange Feed")
                        col_m3.metric("Commodity Class", "Energy" if commodity == "Crude Oil" else "Precious Metal", delta="Hedge Asset")

                        # --- INTERACTIVE 10-YEAR PLOTLY CHART ---
                        st.markdown("---")
                        st.markdown(f"#### 📉 {commodity} 10-Year Price Trend")
                        hist = get_history(ticker)
                        if not hist.empty and "Close" in hist.columns:
                            fig = px.line(
                                hist,
                                x=hist.index,
                                y="Close",
                                title=f"{commodity} - 10 Year Price History",
                                labels={"Close": "Price (USD)", "index": "Year"}
                            )
                            fig.update_traces(line_color="#FFA15C" if commodity == "Crude Oil" else "#FFD700", line_width=2)
                            fig.update_layout(
                                xaxis_title="Year",
                                yaxis_title="Price ($)",
                                hovermode="x unified",
                                margin=dict(l=20, r=20, t=40, b=20)
                            )
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.warning("Historical price chart currently unavailable.")

                        # --- BUY & SELL TRANSACTIONS ---
                        st.markdown("---")
                        col_buy, col_sell = st.columns(2)

                        with col_buy:
                            st.markdown(f"#### Buy {commodity}")
                            quantity_buy = st.number_input(
                                f"Quantity to buy (in {selected_unit})",
                                min_value=0.01,
                                value=1.0 if commodity == "Crude Oil" else 0.10,
                                step=0.01,
                                key="metals_buy_qty"
                            )
                            
                            cost = quantity_buy * price_per_selected_unit
                            st.write(f"**Total Cost:** ${cost:,.2f}")

                            if st.button(f"Buy {commodity}", key="confirm_buy_commodity"):
                                if user["wallet_balance"] < cost:
                                    st.error("Insufficient wallet balance.")
                                else:
                                    base_units_to_buy = quantity_buy * factor
                                    buy_asset(
                                        user["username"], "Metals & Oil",
                                        commodity, ticker, base_units_to_buy, price,
                                    )
                                    user["wallet_balance"] -= cost
                                    update_wallet(user["username"], user["wallet_balance"])
                                    st.success(f"Successfully bought {quantity_buy:.2f} {selected_unit} of {commodity}!")
                                    st.rerun()

                        with col_sell:
                            st.markdown(f"#### Sell {commodity}")
                            commodity_holding = next(
                                (h for h in holdings if h[1] == "Metals & Oil" and h[2] == commodity), None
                            )
                            
                            owned_base_units = commodity_holding[4] if commodity_holding else 0.0
                            owned_display_units = owned_base_units / factor
                            avg_buy_price_display = (commodity_holding[5] / commodity_holding[4]) * factor if owned_base_units > 0 else 0.0

                            if owned_base_units <= 0:
                                st.info(f"You do not own any {commodity} to sell.")
                            else:
                                quantity_sell = st.number_input(
                                    f"Quantity to sell (Owned: {owned_display_units:.2f} {selected_unit})",
                                    min_value=0.01,
                                    max_value=float(owned_display_units),
                                    value=min(1.0 if commodity == "Crude Oil" else 0.10, float(owned_display_units)),
                                    step=0.01,
                                    key="metals_sell_qty"
                                )
                                
                                proceeds = quantity_sell * price_per_selected_unit
                                cost_basis = quantity_sell * avg_buy_price_display
                                pnl = proceeds - cost_basis
                                pnl_pct = (pnl / cost_basis) * 100 if cost_basis > 0 else 0

                                st.write(f"🏷️ **Selling Price:** ${price_per_selected_unit:,.2f} / {selected_unit}")
                                st.write(f"💵 **Proceeds:** ${proceeds:,.2f}")
                                if pnl >= 0:
                                    st.success(f"📈 Profit: +${pnl:,.2f} (+{pnl_pct:.2f}%)")
                                else:
                                    st.error(f"📉 Loss: -${abs(pnl):,.2f} ({pnl_pct:.2f}%)")

                                if st.button(f"Confirm Sell {commodity}", key="confirm_sell_commodity"):
                                    base_units_to_sell = quantity_sell * factor
                                    success, msg, rec_proceeds = sell_asset(
                                        user["username"], "Metals & Oil", commodity, ticker, base_units_to_sell, price
                                    )
                                    if success:
                                        user["wallet_balance"] += rec_proceeds
                                        update_wallet(user["username"], user["wallet_balance"])
                                        st.success(f"Successfully sold {quantity_sell:.2f} {selected_unit} of {commodity}.")
                                        st.rerun()
                                    else:
                                        st.error(msg)

                elif asset == "Real Estate":
                    st.markdown("### 🏠 Virtual Real Estate Marketplace")
                    st.caption("Browse an expanded catalog of 150+ real-world property listings across 20+ major cities, filter by location, category, and budget, and build your virtual passive income portfolio.")

                    # --- EXPANDED MASSIVE PROCEDURAL REAL ESTATE CATALOG GENERATOR (150+ Properties) ---
                    @st.cache_data
                    def get_virtual_marketplace_properties():
                        locations = [
                            ("San Francisco, CA", 37.7749, -122.4194),
                            ("Los Angeles, CA", 34.0522, -118.2437),
                            ("New York, NY", 40.7128, -74.0060),
                            ("Chicago, IL", 41.8781, -87.6298),
                            ("Houston, TX", 29.7604, -95.3698),
                            ("Philadelphia, PA", 39.9526, -75.1652),
                            ("San Diego, CA", 32.7157, -117.1611),
                            ("Austin, TX", 30.2672, -97.7431),
                            ("Miami, FL", 25.7617, -80.1918),
                            ("Seattle, WA", 47.6062, -122.3321),
                            ("Denver, CO", 39.7392, -104.9903),
                            ("Boston, MA", 42.3601, -71.0589),
                            ("Phoenix, AZ", 33.4483, -112.0740),
                            ("Dallas, TX", 32.7767, -96.7970),
                            ("Atlanta, GA", 33.7490, -84.3880),
                            ("Nashville, TN", 36.1627, -86.7816),
                            ("Las Vegas, NV", 36.1699, -115.1398),
                            ("Washington, DC", 38.9072, -77.0369),
                            ("Portland, OR", 45.5152, -122.6784),
                            ("Charlotte, NC", 35.2271, -80.8431)
                        ]

                        templates = [
                            ("Commercial Retail Storefront", "Shop", (180000, 450000), (0.007, 0.010), "High foot traffic zone; strong commercial tenant demand."),
                            ("Boutique Corner Cafe Plot", "Shop", (150000, 320000), (0.0065, 0.009), "Historic district location with high tourism volume."),
                            ("Urban Strip Mall Unit", "Shop", (350000, 800000), (0.0075, 0.0105), "Anchored by popular grocery and retail brands."),
                            ("Suburban Single Family Home", "House", (320000, 750000), (0.005, 0.007), "Top-rated school district; long-term family leases."),
                            ("Luxury Townhouse", "House", (550000, 1200000), (0.0045, 0.0065), "Gated community with high residential equity growth."),
                            ("Suburban Family Duplex", "House", (400000, 900000), (0.0055, 0.0075), "Dual rental units on a single plot for doubled cash flow."),
                            ("Downtown Studio Apartment", "Apartment", (210000, 420000), (0.006, 0.0085), "Ideal for tech workers and university graduate students."),
                            ("Luxury Skyline Penthouse", "Apartment", (900000, 2200000), (0.0035, 0.0055), "Exclusive high-rise living with premium rental yields."),
                            ("Multi-Unit Residential Complex", "Apartment", (650000, 1500000), (0.0075, 0.011), "Multiple rental units producing steady aggregated cash flow."),
                            ("Agricultural Crop Farmland", "Farm", (250000, 600000), (0.004, 0.006), "Leased to local farming cooperatives for annual yields."),
                            ("Organic Vineyard Plot", "Farm", (400000, 950000), (0.005, 0.008), "High-value agricultural leasing with agri-tourism potential."),
                            ("Industrial Distribution Logistics Hub", "Land", (300000, 850000), (0.006, 0.009), "Zoned for freight transport and e-commerce distribution."),
                            ("Highway Commercial Plot", "Land", (120000, 350000), (0.005, 0.0075), "Prime highway visibility for fuel stations or drive-thrus."),
                            ("Suburban Medical Clinic Plot", "Commercial", (500000, 1100000), (0.006, 0.0085), "Long-term lease agreements with healthcare providers."),
                            ("Automated Self-Storage Facility", "Commercial", (350000, 900000), (0.007, 0.0095), "Low overhead operational costs with high monthly occupancy rates.")
                        ]

                        catalog = []
                        prop_id = 1
                        
                        # Seeded loop to generate a massive, diverse inventory of 150+ properties
                        random.seed(2026)
                        for loc_name, lat, lon in locations:
                            # Select 8 diverse templates per city for a much larger selection pool
                            selected_templates = random.choices(templates, k=8)
                            for title, cat, (p_min, p_max), (r_min, r_max), factor in selected_templates:
                                price = round(random.uniform(p_min, p_max), -3)
                                monthly_rent = round(price * random.uniform(r_min, r_max), -1)
                                
                                lat_jitter = lat + random.uniform(-0.06, 0.06)
                                lon_jitter = lon + random.uniform(-0.06, 0.06)

                                catalog.append({
                                    "id": prop_id,
                                    "name": f"{title} #{prop_id}",
                                    "category": cat,
                                    "location": loc_name,
                                    "listing_type": random.choice(["For Sale", "For Rent / Sale"]),
                                    "lat": lat_jitter,
                                    "lon": lon_jitter,
                                    "price": float(price),
                                    "rent": float(monthly_rent),
                                    "demand_factor": factor
                                })
                                prop_id += 1

                        return catalog

                    properties_data = get_virtual_marketplace_properties()
                    df_props = pd.DataFrame(properties_data)

                    # --- LOCATION SEARCH & FILTER BAR ---
                    st.markdown("#### 🔍 Real Estate Search & Inventory Filters")
                    
                    all_locations = ["All Locations"] + sorted(list(df_props["location"].unique()))
                    all_categories = ["All Types", "Shop", "House", "Apartment", "Farm", "Land", "Commercial"]
                    
                    col_s1, col_s2, col_s3 = st.columns(3)
                    
                    with col_s1:
                        selected_location = st.selectbox("Filter by City / Location", all_locations, key="re_location_search")
                    with col_s2:
                        filter_cat = st.selectbox("Property Type", all_categories, key="re_cat_filter")
                    with col_s3:
                        max_budget = st.slider("Max Price Budget ($)", min_value=100000, max_value=2500000, value=2000000, step=50000, key="re_budget_filter")

                    # Filter execution
                    filtered_df = df_props[df_props["price"] <= max_budget].copy()
                    
                    if selected_location != "All Locations":
                        filtered_df = filtered_df[filtered_df["location"] == selected_location]
                        
                    if filter_cat != "All Types":
                        filtered_df = filtered_df[filtered_df["category"] == filter_cat]

                    # Calculate yield
                    filtered_df["yield_pct"] = (filtered_df["rent"] * 12 / filtered_df["price"]) * 100

                    st.success(f"Marketplace Active: Showing **{len(filtered_df)}** available properties matching your criteria.")

                    # --- MAP DISPLAY ---
                    st.markdown("#### 🗺️ Regional Property Map")
                    if not filtered_df.empty:
                        st.map(filtered_df[["lat", "lon"]])
                    else:
                        st.info("No properties found in this area under your budget constraint. Try adjusting your filters.")

                    st.markdown("---")
                    
                    # --- MARKETPLACE PROPERTY SELECTION ---
                    if not filtered_df.empty:
                        prop_options = {
                            row["id"]: f"{row['name']} ({row['location']}) — ${row['price']:,.2f} | Yield: {row['yield_pct']:.2f}%"
                            for _, row in filtered_df.iterrows()
                        }
                        
                        selected_prop_id = st.selectbox(
                            "Select a Property from Catalog to Inspect & Buy:",
                            list(prop_options.keys()),
                            format_func=lambda x: prop_options[x],
                            key="re_prop_select"
                        )
                        
                        selected_prop = next(p for p in properties_data if p["id"] == selected_prop_id)

                        # Property Analytics Card
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.metric("🏷️ Purchase Price", f"${selected_prop['price']:,.2f}")
                        with c2:
                            st.metric("💵 Est. Monthly Rent", f"${selected_prop['rent']:,.2f}")
                        with c3:
                            yield_pct = (selected_prop['rent'] * 12 / selected_prop['price']) * 100
                            st.metric("📊 Annual Rental Yield", f"{yield_pct:.2f}% / year")

                        st.info(f"📍 **Location:** {selected_prop['location']} | **Category:** {selected_prop['category']} | **Status:** {selected_prop['listing_type']}")
                        st.markdown(f"**📈 Investment Insight & Demand Analysis:**\n> {selected_prop['demand_factor']}")

                        # Buy Execution
                        if st.button(f"Acquire Property: {selected_prop['name']}", key=f"buy_prop_{selected_prop['id']}"):
                            if user["wallet_balance"] < selected_prop['price']:
                                st.error("Insufficient wallet balance to acquire this property.")
                            else:
                                buy_asset(
                                    user["username"], "Real Estate", selected_prop["category"],
                                    f"PROP-{selected_prop['id']}", 1.0, selected_prop['price'],
                                )
                                user["wallet_balance"] -= selected_prop['price']
                                update_wallet(user["username"], user["wallet_balance"])
                                st.success(f"Successfully acquired {selected_prop['name']} into your portfolio!")
                                st.rerun()

# ---------------- AI Advisor Tab ----------------
st.subheader("🤖 AI Financial Advisor (Powered by NVIDIA Nemotron)")
st.caption("Your personal GPU-accelerated mentor ready to evaluate strategies, explain market terms, and guide your financial growth.")

# --- 1. AI PERSONA SELECTOR ---
col_p1, col_p2 = st.columns([1, 2])
with col_p1:
    ai_persona = st.selectbox(
        "Choose AI Mentor Style",
        [
            "Pragmatic & Safety-First Mentor",
            "Aggressive Wealth Builder",
            "Passive Income & Dividend Specialist"
        ],
        key="ai_persona_selector"
    )

with col_p2:
    st.markdown(f"**Active Mode:** `{ai_persona}` — Tailoring responses to your chosen strategy.")

st.markdown("---")

# Initialize session state for storing the active prompt if not present
if "ai_prompt_to_run" not in st.session_state:
    st.session_state.ai_prompt_to_run = ""

# --- 2. QUICK SUGGESTION PILLS ---
st.markdown("##### 💡 Quick Questions to Get Started:")
quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)

with quick_col1:
    if st.button("What is a P/E Ratio?"):
        st.session_state.ai_prompt_to_run = "Explain what a P/E ratio is in simple terms for a beginner investor."
with quick_col2:
    if st.button("How to build passive income?"):
        st.session_state.ai_prompt_to_run = "What are the best safe ways to build a reliable stream of passive income?"
with quick_col3:
    if st.button("Is market risky right now?"):
        st.session_state.ai_prompt_to_run = "How should a beginner handle market volatility and risk?"
with quick_col4:
    if st.button("Diversification Tips"):
        st.session_state.ai_prompt_to_run = "Why is portfolio diversification important across stocks, real estate, and commodities?"

st.markdown("---")

# --- 3. CUSTOM TYPED INPUT BOX ---
user_question = st.text_input(
    "Or type your own question here:", 
    placeholder="e.g., Is it risky to put all my virtual money into tech stocks?"
)

# If the user typed something, override the quick button state
if user_question.strip():
    st.session_state.ai_prompt_to_run = user_question.strip()

# --- 4. EXECUTION BUTTON ---
ask_clicked = st.button("Ask NVIDIA Nemotron", type="primary")

# --- 5. DISPLAY AI RESPONSE NORMALLY ACROSS FULL WIDTH ---
if ask_clicked or st.session_state.ai_prompt_to_run:
    target_prompt = st.session_state.ai_prompt_to_run
    
    if target_prompt:
        with st.spinner("NVIDIA Nemotron is analyzing market data and generating advice..."):
            try:
                system_content = f"You are an expert financial mentor operating in '{ai_persona}' mode. Keep answers concise, highly structured, encouraging, and easy for beginners to understand."
                
                completion = client.chat.completions.create(
                    model="nvidia/nemotron-3.5-lightning-30b-a3b",
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": target_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2048,
                    extra_body={
                        "chat_template_kwargs": {
                            "enable_thinking": False
                        }
                    }
                )
                
                ai_answer = completion.choices[0].message.content
                
                if ai_answer:
                    st.markdown("---")
                    st.markdown(f"### 🧠 NVIDIA AI Advisor Insights")
                    st.caption(f"**Query:** *{target_prompt}*")
                    
                    # Display the response normally in a clean, full-width container box
                    st.success(ai_answer)
                    st.info("📌 **Actionable Tip:** Practice applying this advice directly inside your Portfolio or Marketplace tabs!")
                    
                    # Clear the trigger state so it doesn't loop awkwardly on future reruns
                    st.session_state.ai_prompt_to_run = ""
                else:
                    st.warning("The AI returned an empty response. Please try asking again.")
                    
            except Exception as e:
                st.error(f"Error communicating with NVIDIA API: {e}")
    else:
        st.warning("Please type a question or click one of the quick suggestion buttons above!")
