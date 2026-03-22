#!/usr/bin/env python3
"""
Build Groww Strategy Files — Top 99 Scripts
Each file is a complete, copy-pasteable Python strategy for Groww Dashboard.

Usage: python3 build_strategies.py
Output: deploy/strategies/ directory with 99 strategy files
"""
import os, json, shutil

DEPLOY = "/home/node/workspace/trade-project/deploy"
STRATEGY_DIR = DEPLOY + "/strategies"

# Master pool — top 99 stocks ranked by win rate
MASTER_POOL = [
    ("ADANIPOWER", "NS", 0.9167, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ADANIGREEN", "NS", 0.7000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ADANIPORTS", "NS", 0.6667, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("RELIANCE", "NS", 0.6364, "TSI_VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "10 AM - 1 PM"}),
    ("TCS", "NS", 0.6364, "VWAP_RSI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "10 AM - 1 PM"}),
    ("SBIN", "NS", 0.6364, "VWAP_PSU", {"entry_vwap_pct": 0.3, "rsi_min": 50, "rsi_max": 38, "vol_mult": 1.1, "entry_window": "10 AM - 2 PM"}),
    ("GODREJPROP", "NS", 0.6316, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("UCOBANK", "NS", 0.6304, "ADX_TREND", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("COLPAL", "NS", 0.6296, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("HAVELLS", "NS", 0.6207, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("TATASTEEL", "NS", 0.6154, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("TITAN", "NS", 0.6111, "VWAP_GOLD", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 12 PM"}),
    ("HDFCBANK", "NS", 0.6061, "ADX_TREND", {"entry_vwap_pct": 0.5, "rsi_min": 60, "rsi_max": 40, "vol_mult": 1.5, "entry_window": "9:30 AM - 2:30 PM"}),
    ("IGL", "NS", 0.6020, "ADX_TREND", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("SRF", "NS", 0.6013, "MACD_MOMENTUM", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("CIPLA", "NS", 0.6007, "MOMENTUM_DIVERGENCE", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("COALINDIA", "NS", 0.6000, "VWAP_PSU", {"entry_vwap_pct": 0.3, "rsi_min": 50, "rsi_max": 40, "vol_mult": 1.1, "entry_window": "10 AM - 2 PM"}),
    ("BANKINDIA", "NS", 0.6000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("NESTLEIND", "NS", 0.5926, "MOMENTUM_DIVERGENCE", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("MARUTI", "NS", 0.5882, "VWAP_AUTO", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "10 AM - 1 PM"}),
    ("BOSCHLTD", "NS", 0.5882, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("HINDALCO", "NS", 0.5862, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("HCLTECH", "NS", 0.5833, "VWAP_RSI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "10 AM - 1 PM"}),
    ("HEROMOTOCO", "NS", 0.5800, "VWAP_RSI_MACD", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("M&M", "NS", 0.5769, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("LUPIN", "NS", 0.5769, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("LT", "NS", 0.5714, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("SUNPHARMA", "NS", 0.5714, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("KOTAKBANK", "NS", 0.5667, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("DIVISLAB", "NS", 0.5625, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("AXISBANK", "NS", 0.5625, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BAJFINANCE", "NS", 0.5600, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ICICIBANK", "NS", 0.5588, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("SBILIFE", "NS", 0.5556, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BHARTIARTL", "NS", 0.5500, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ONGC", "NS", 0.5500, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("POWERGRID", "NS", 0.5500, "FIBONACCI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("NTPC", "NS", 0.5500, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ITC", "NS", 0.5455, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("INFY", "NS", 0.5455, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "10 AM - 1 PM"}),
    ("ADANIENT", "NS", 0.5300, "TSI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ASIANPAINT", "NS", 0.5300, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("SHREECEM", "NS", 0.5300, "TSI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ABB", "NS", 0.5300, "ADX_TREND", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ALKEM", "NS", 0.5250, "PARABOLIC_SAR", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BPCL", "NS", 0.5200, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("CHOLAFIN", "NS", 0.5150, "FIBONACCI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("GRASIM", "NS", 0.5150, "FIBONACCI_VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("DABUR", "NS", 0.5100, "ADX_TREND", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ACC", "NS", 0.5000, "MA_ENVELOPE", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BEL", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("CANBK", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("FEDERALBNK", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("GMRINFRA", "NS", 0.5000, "VWAP_RSI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("IOB", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("PERSISTENT", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("HINDPETRO", "NS", 0.5000, "FIBONACCI", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("DRREDDY", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("MGL", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("PETRONET", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("AUBANK", "NS", 0.5000, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("HAL", "NS", 0.4950, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("NAUKRI", "NS", 0.4950, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("DMART", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("PIDILITIND", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("PAGEIND", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("SIEMENS", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("INDUSIND", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BANKBARODA", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("LICI", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("CGPOWER", "NS", 0.4900, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("JINDALSTL", "NS", 0.4850, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("TATAELXSI", "NS", 0.4850, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("AMBUJACEM", "NS", 0.4850, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("UBL", "NS", 0.4800, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ICICIPRULI", "NS", 0.4800, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("GAIL", "NS", 0.4800, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ASHOKLEY", "NS", 0.4800, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BANDHANBNK", "NS", 0.4800, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("FORTIS", "NS", 0.4750, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ZYDUS", "NS", 0.4750, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("MARICO", "NS", 0.4750, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("VOLTAS", "NS", 0.4750, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("METROBRANDS", "NS", 0.4750, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("MAXHEALTH", "NS", 0.4750, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("CROMPTON", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("BAJAJFINSV", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("JSWENERGY", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("NMDC", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("COFORGE", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("OFSS", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("AJANTAPHARM", "NS", 0.4700, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("GODREJCP", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("INDIAMART", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("LTI", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("ESCORTS", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("DEEPAKNTR", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("RECL", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("PFC", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
    ("IRCTC", "NS", 0.4650, "VWAP", {"entry_vwap_pct": 0.5, "rsi_min": 55, "rsi_max": 45, "vol_mult": 1.2, "entry_window": "9:30 AM - 2:30 PM"}),
]


def build_strategy_file(symbol, exchange, win_rate, strategy_name, params):
    """Build a single Groww-compatible strategy file"""
    
    fname = f"groww_{symbol}_{exchange}.py"
    fpath = os.path.join(STRATEGY_DIR, fname)
    
    entry_cond = f"> VWAP + {params['entry_vwap_pct']}%"
    rsi_cond = f"> {params['rsi_min']} (BUY) / < {params['rsi_max']} (SELL)"
    
    content = f'''#!/usr/bin/env python3
"""
Groww Strategy: {symbol}
Exchange: {exchange} | Strategy: {strategy_name}
Win Rate: {win_rate*100:.2f}% | Backtest Period: 90 days

COPY-PASTE TO GROWW DASHBOARD:
  1. Go to groww.in/webtel/trade-api/strategies
  2. Click "Create Strategy" 
  3. Paste this entire file as the Python strategy
  4. Set GROWW_API_KEY and GROWW_API_SECRET below
  5. Activate strategy

ENTRY RULES:
  • Price {entry_cond}
  • RSI(14) {rsi_cond}
  • Volume > {params['vol_mult']}x 20-day average
  • NIFTY > 20-day SMA (uptrend only)
  • Time: {params['entry_window']} IST

EXIT RULES:
  • Target 1: 1.5× risk — exit 1/3 position
  • Target 2: 3.0× risk — exit 1/3 position  
  • Target 3: 5.0× risk — exit remaining 1/3
  • Stop loss: 1.0× ATR (0.8% of price)
  • Max daily loss: ₹3,000 — hard stop

COPY-PASTE CONFIG (Groww Dashboard):
  symbol = "{symbol}"
  exchange = "{exchange}"
  strategy = "{strategy_name}"
  win_rate = {win_rate:.4f}
  position_size = 10000  # ₹10,000 per trade
  entry_vwap_pct = {params['entry_vwap_pct']}
  entry_rsi_min = {params['rsi_min']}
  entry_rsi_max = {params['rsi_max']}
  vol_mult = {params['vol_mult']}
  stop_loss_adr = 0.008  # 0.8% of price
  target_rr = [1.5, 3.0, 5.0]  # risk multiples
"""

import os
import sys
import time
import json
import hmac
import hashlib
import base64
import requests
from datetime import datetime, timedelta

# =============================================================================
# GROWW API CONFIGURATION — Set your credentials
# =============================================================================
GROWW_API_KEY = os.getenv("GROWW_API_KEY", "YOUR_KEY_HERE")
GROWW_API_SECRET = os.getenv("GROWW_API_SECRET", "YOUR_SECRET_HERE")
SY