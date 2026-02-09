# Algoritmos Financieros / Quant Trading Modernos
## Resumen para Integración en Sistema de Trading

---

## 1. ALGORITMOS DE MOMENTUM AVANZADOS

### 1.1 Dual Momentum (Gary Antonacci)

**Descripción:**
Combina momentum relativo (cross-sectional) con momentum absoluto (time series). Selecciona el mejor activo entre un universo basado en rendimiento relativo, pero solo invierte si el activo tiene momentum positivo absoluto.

**Fórmula/Lógica:**
```
Momentum Relativo = Retorno_Activo_i / Retorno_Activo_benchmark
Momentum Absoluto = Retorno_Activo > 0 (típicamente sobre 12 meses)

Regla GEM (Global Equity Momentum):
1. Calcular momentum de 12 meses para S&P 500 y MSCI ACWI ex-US
2. Seleccionar el de mayor rendimiento (Relative Strength)
3. Si el seleccionado tiene retorno > 0 → Invertir
4. Si no → Invertir en Bonos (Aggregate Bond Index)
```

**Parámetros Típicos:**
- Lookback period: 12 meses (también se usa 6-12 meses)
- Frecuencia de rebalanceo: Mensual
- Universo típico: S&P 500, MSCI ACWI ex-US, Bloomberg Agg Bond

**Implementación Python:**
```python
import pandas as pd
import numpy as np

def dual_momentum(prices, lookback=252):
    """
    prices: DataFrame con precios de activos
    lookback: período en días (252 ≈ 12 meses)
    """
    # Calcular retornos del período
    returns = prices.pct_change(lookback)
    
    # Momentum relativo: seleccionar mejor activo
    relative_momentum = returns.iloc[-1]
    best_asset = relative_momentum.idxmax()
    
    # Momentum absoluto: verificar si > 0
    absolute_momentum = relative_momentum[best_asset]
    
    if absolute_momentum > 0:
        return best_asset  # Invertir en el mejor
    else:
        return "BONDS"  # Ir a bonos o cash
```

**Referencias:**
- Antonacci, G. (2014). *Dual Momentum Investing*. McGraw-Hill
- Antonacci, G. (2012). "Risk Premia Harvesting Through Dual Momentum"

---

### 1.2 Relative Strength Momentum

**Descripción:**
Clasifica activos por su rendimiento pasado y asigna capital a los mejores performers. Basado en la anomalía del momentum donde los ganadores recientes continúan superando.

**Fórmula/Lógica:**
```
RS_Ratio = (Precio_hoy / Precio_n_periodos) / (Benchmark_hoy / Benchmark_n_periodos)

Ranking por retorno total en período de lookback
Top quartile/decile → Overweight
Bottom quartile/decile → Underweight/Short
```

**Parámetros Típicos:**
- Lookback: 3-12 meses
- Holding period: 1-12 meses
- Número de activos seleccionados: Top 10-30%

**Implementación Python:**
```python
def relative_strength_momentum(prices, lookback=126, top_n=5):
    """
    Selecciona top N activos por momentum
    """
    momentum = prices.pct_change(lookback).iloc[-1]
    top_assets = momentum.nlargest(top_n).index.tolist()
    
    # Pesos iguales o proporcionales al momentum
    weights = pd.Series(0, index=prices.columns)
    weights[top_assets] = 1 / top_n
    return weights
```

---

### 1.3 Absolute Momentum (Time Series Momentum)

**Descripción:**
Evalúa si un activo tiene tendencia positiva o negativa en sí mismo, sin comparar con otros. Señal binaria: long si momentum > 0, short/cash si < 0.

**Fórmula/Lógica:**
```
Señal = sign(Retorno_lookback)
Posición = Long si Retorno > 0, Short/Cash si Retorno < 0
```

**Parámetros Típicos:**
- Lookback: 12 meses (más efectivo según Moskowitz & Grinblatt)
- Frecuencia: Mensual

**Referencias:**
- Moskowitz, T.J. & Grinblatt, M. (1999). "Do Industries Explain Momentum?" *Journal of Finance*
- Hurst, B., Ooi, Y.H. & Pedersen, L.H. (2013). "Demystifying Managed Futures" *Journal of Investment Management*

---

### 1.4 Time Series Momentum vs Cross-Sectional Momentum

| Característica | Time Series | Cross-Sectional |
|---------------|-------------|-----------------|
| Comparación | Consigo mismo | Entre activos |
| Señal | Direccional | Relative ranking |
| Posiciones | Long/Short/Cash | Long top, Short bottom |
| Exposición de mercado | Variable | Neutral de mercado |

**Implementación combinada:**
```python
def combined_momentum(prices, lookback_ts=252, lookback_cs=126, top_n=5):
    # Time Series Momentum
    ts_momentum = prices.pct_change(lookback_ts).iloc[-1]
    ts_signals = np.where(ts_momentum > 0, 1, -1)
    
    # Cross-Sectional Momentum
    cs_momentum = prices.pct_change(lookback_cs).iloc[-1]
    cs_ranks = cs_momentum.rank(ascending=False)
    
    # Combinar: solo activos con TS positivo y en top CS
    weights = pd.Series(0, index=prices.columns)
    for asset in prices.columns:
        if ts_signals[asset] > 0 and cs_ranks[asset] <= top_n:
            weights[asset] = 1 / top_n
    
    return weights
```

---

## 2. ESTRATEGIAS DE FACTOR INVESTING

### 2.1 Fama-French 3-Factor y 5-Factor

**Descripción:**
Modelo de pricing de activos que explica los retornos a través de exposición a factores sistémicos. El modelo 5-factor añade rentabilidad e inversión a los factores originales.

**Fórmula:**
```
3-Factor:
E(R) = Rf + β_mkt(Rm - Rf) + β_smb·SMB + β_hml·HML

5-Factor:
E(R) = Rf + β_mkt(Rm - Rf) + β_smb·SMB + β_hml·HML + β_rmw·RMW + β_cma·CMA

Donde:
- SMB (Small Minus Big): Factor tamaño
- HML (High Minus Low): Factor valor (book-to-market)
- RMW (Robust Minus Weak): Factor rentabilidad
- CMA (Conservative Minus Aggressive): Factor inversión
```

**Construcción de Factores:**
```python
def calculate_smb_hml(stock_data):
    """
    stock_data: DataFrame con columnas ['market_cap', 'book_to_market', 'returns']
    """
    # Clasificar por tamaño (median market cap)
    size_median = stock_data['market_cap'].median()
    small = stock_data['market_cap'] <= size_median
    big = stock_data['market_cap'] > size_median
    
    # Clasificar por B/M (30-40-30 percentiles)
    bm_30 = stock_data['book_to_market'].quantile(0.3)
    bm_70 = stock_data['book_to_market'].quantile(0.7)
    
    value = stock_data['book_to_market'] >= bm_70
    growth = stock_data['book_to_market'] <= bm_30
    
    # Calcular SMB y HML
    small_value = stock_data[small & value]['returns'].mean()
    small_growth = stock_data[small & growth]['returns'].mean()
    big_value = stock_data[big & value]['returns'].mean()
    big_growth = stock_data[big & growth]['returns'].mean()
    
    SMB = (small_value + small_growth)/2 - (big_value + big_growth)/2
    HML = (small_value + big_value)/2 - (small_growth + big_growth)/2
    
    return SMB, HML
```

**Referencias:**
- Fama, E.F. & French, K.R. (1993). "Common Risk Factors in the Returns on Stocks and Bonds" *Journal of Financial Economics*
- Fama, E.F. & French, K.R. (2015). "A Five-Factor Asset Pricing Model" *Journal of Financial Economics*

---

### 2.2 Quality Factor

**Descripción:**
Invierte en empresas con alta rentabilidad, bajo apalancamiento y earnings estables. Empresas de alta calidad tienen retornos superiores ajustados por riesgo.

**Métricas de Quality:**
```
Quality Score = w1·ROE + w2·ROA + w3·Earnings_Stability + w4·Low_Leverage

Componentes:
- ROE = Net Income / Shareholders' Equity
- ROA = Net Income / Total Assets
- Earnings Stability = -StdDev(ROE_5years)
- Leverage = Total Debt / Total Assets (invertido)
```

**Implementación:**
```python
def quality_score(financials):
    """
    financials: DataFrame con datos financieros
    """
    roe = financials['net_income'] / financials['equity']
    roa = financials['net_income'] / financials['total_assets']
    
    # Estabilidad de earnings (menor volatilidad = mayor score)
    earnings_vol = financials['roe_history'].std(axis=1)
    earnings_stability = -earnings_vol
    
    # Bajo apalancamiento
    leverage = financials['total_debt'] / financials['total_assets']
    
    # Score compuesto
    quality = (0.4 * roe + 
               0.3 * roa + 
               0.2 * earnings_stability + 
               0.1 * (1 - leverage))
    
    return quality.rank(pct=True)
```

**Referencias:**
- Asness, C.S. (2019). "Quality Minus Junk" *Review of Accounting Studies*
- Sloan, R.G. (1996). "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows About Future Earnings?" *The Accounting Review*

---

### 2.3 Low Volatility Factor

**Descripción:**
Las acciones con baja volatilidad histórica tienen retornos superiores a los predichos por CAPM (anomalía "low vol").

**Métricas:**
```
Volatility Score = StdDev(retornos_diarios) * sqrt(252)
Low Vol Portfolio = Bottom quintil por volatilidad
```

**Implementación:**
```python
def low_volatility_weights(returns, lookback=252):
    """
    Inverse volatility weighting
    """
    volatility = returns.iloc[-lookback:].std() * np.sqrt(252)
    inv_vol = 1 / volatility
    weights = inv_vol / inv_vol.sum()
    return weights
```

---

### 2.4 Size Factor (SMB)

**Descripción:**
Las empresas pequeñas (small caps) históricamente superan a las grandes, compensación por menor liquidez y mayor riesgo.

**Implementación:**
```python
def size_factor_weights(market_caps, small_threshold_percentile=50):
    """
    Overweight en small caps
    """
    median_cap = market_caps.median()
    small_mask = market_caps <= median_cap
    
    weights = pd.Series(0, index=market_caps.index)
    weights[small_mask] = 2 / small_mask.sum()
    weights[~small_mask] = 0  # O menor peso
    
    return weights
```

---

### 2.5 Value Factor Mejorado

**Descripción:**
Extensión del tradicional P/B (Price/Book) con múltiples métricas de valor.

**Métricas Combinadas:**
```
Value Score = w1·E/P + w2·B/P + w3·S/P + w4·EBIT/EV + w5·CF/P

Donde:
- E/P: Earnings Yield (inverso de P/E)
- B/P: Book-to-Market
- S/P: Sales-to-Price
- EBIT/EV: Enterprise Yield
- CF/P: Cash Flow Yield
```

**Implementación:**
```python
def enhanced_value_score(data):
    """
    data: DataFrame con ratios de valoración
    """
    ep = data['earnings'] / data['market_cap']  # Earnings Yield
    bp = data['book_value'] / data['market_cap']  # Book-to-Market
    sp = data['sales'] / data['market_cap']  # Sales-to-Price
    ebit_ev = data['ebit'] / data['enterprise_value']
    cfp = data['cash_flow'] / data['market_cap']
    
    # Z-score de cada métrica
    ep_z = (ep - ep.mean()) / ep.std()
    bp_z = (bp - bp.mean()) / bp.std()
    sp_z = (sp - sp.mean()) / sp.std()
    ebit_ev_z = (ebit_ev - ebit_ev.mean()) / ebit_ev.std()
    cfp_z = (cfp - cfp.mean()) / cfp.std()
    
    # Score compuesto
    value_score = (ep_z + bp_z + sp_z + ebit_ev_z + cfp_z) / 5
    
    return value_score.rank(pct=True)
```

---

## 3. MACHINE LEARNING EN TRADING

### 3.1 Random Forest para Clasificación de Señales

**Descripción:**
Ensemble de árboles de decisión que clasifica la dirección del precio o genera señales de trading basadas en features técnicos/fundamentales.

**Features Típicos:**
```python
features = [
    # Features de precio
    'returns_1d', 'returns_5d', 'returns_21d', 'returns_63d',
    'volatility_21d', 'volatility_63d',
    
    # Features técnicos
    'rsi_14', 'macd', 'macd_signal', 'bb_position',
    'atr_14', 'adx_14',
    
    # Features de volumen
    'volume_sma_ratio', 'obv', 'vwap_ratio',
    
    # Features de mercado
    'spy_correlation', 'vix_level', 'yield_spread'
]
```

**Implementación:**
```python
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
import pandas as pd
import numpy as np

def prepare_ml_data(prices, features, forward_return_days=5):
    """
    Prepara datos para ML
    """
    # Target: dirección del retorno forward
    forward_returns = prices['close'].pct_change(forward_return_days).shift(-forward_return_days)
    target = (forward_returns > 0).astype(int)  # 1 si sube, 0 si baja
    
    return features, target

def train_rf_classifier(X_train, y_train, X_test):
    """
    Entrena Random Forest con validación temporal
    """
    # Parámetros típicos
    rf = RandomForestClassifier(
        n_estimators=100,
        max_depth=5,
        min_samples_split=50,
        min_samples_leaf=20,
        max_features='sqrt',
        random_state=42,
        n_jobs=-1
    )
    
    rf.fit(X_train, y_train)
    predictions = rf.predict(X_test)
    probabilities = rf.predict_proba(X_test)[:, 1]
    
    # Feature importance
    feature_importance = pd.Series(
        rf.feature_importances_,
        index=X_train.columns
    ).sort_values(ascending=False)
    
    return predictions, probabilities, feature_importance

# Uso con walk-forward validation
def walk_forward_rf(prices, features, train_size=252, step=21):
    """
    Walk-forward validation para series temporales
    """
    predictions = []
    
    for i in range(train_size, len(prices) - 21, step):
        X_train = features.iloc[i-train_size:i]
        y_train = target.iloc[i-train_size:i]
        X_test = features.iloc[i:i+step]
        
        pred, prob, _ = train_rf_classifier(X_train, y_train, X_test)
        predictions.extend(pred)
    
    return predictions
```

**Parámetros Típicos:**
- n_estimators: 100-500
- max_depth: 3-10 (evitar overfitting)
- min_samples_split: 20-100
- min_samples_leaf: 10-50

---

### 3.2 XGBoost / LightGBM

**Descripción:**
Gradient boosting optimizado para velocidad y performance. Excelente para capturar relaciones no lineales en datos financieros.

**Ventajas sobre Random Forest:**
- Mayor velocidad de entrenamiento
- Regularización integrada (L1/L2)
- Manejo nativo de valores faltantes
- Early stopping

**Implementación XGBoost:**
```python
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit

def train_xgb_classifier(X_train, y_train, X_val, y_val):
    """
    Entrena XGBoost con early stopping
    """
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dval = xgb.DMatrix(X_val, label=y_val)
    
    params = {
        'objective': 'binary:logistic',
        'eval_metric': 'auc',
        'max_depth': 4,
        'eta': 0.05,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'lambda': 1,  # L2 regularization
        'alpha': 0.5,  # L1 regularization
        'seed': 42
    }
    
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=1000,
        evals=[(dval, 'validation')],
        early_stopping_rounds=50,
        verbose_eval=False
    )
    
    return model

# Feature importance con SHAP
import shap

def explain_xgb_model(model, X):
    """
    Explicabilidad con SHAP values
    """
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)
    
    shap.summary_plot(shap_values, X)
    return shap_values
```

**Implementación LightGBM:**
```python
import lightgbm as lgb

def train_lgb_classifier(X_train, y_train, X_val, y_val):
    """
    LightGBM - más rápido para datasets grandes
    """
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'lambda_l1': 0.5,
        'lambda_l2': 1.0
    }
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)]
    )
    
    return model
```

**Referencias:**
- Gu, S., Kelly, B. & Xiu, D. (2020). "Empirical Asset Pricing via Machine Learning" *Review of Financial Studies*
- Chen, T. & Guestrin, C. (2016). "XGBoost: A Scalable Tree Boosting System"

---

### 3.3 Redes LSTM para Series Temporales

**Descripción:**
Long Short-Term Memory networks capturan dependencias temporales largas en series de precios. Útiles para predicción de retornos o volatilidad.

**Arquitectura Típica:**
```
Input (sequence_length, n_features)
    ↓
LSTM Layer 1 (units=64, return_sequences=True)
    ↓
Dropout (0.2)
    ↓
LSTM Layer 2 (units=32, return_sequences=False)
    ↓
Dropout (0.2)
    ↓
Dense Layer (units=16, activation='relu')
    ↓
Output Dense (units=1, activation='sigmoid' o 'linear')
```

**Implementación:**
```python
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
from sklearn.preprocessing import StandardScaler

def create_lstm_model(sequence_length, n_features):
    """
    Crea modelo LSTM para predicción de dirección
    """
    model = Sequential([
        LSTM(64, return_sequences=True, 
             input_shape=(sequence_length, n_features)),
        BatchNormalization(),
        Dropout(0.2),
        
        LSTM(32, return_sequences=False),
        BatchNormalization(),
        Dropout(0.2),
        
        Dense(16, activation='relu'),
        Dropout(0.2),
        
        Dense(1, activation='sigmoid')  # Para clasificación
        # Dense(1, activation='linear')  # Para regresión
    ])
    
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
        loss='binary_crossentropy',  # o 'mse' para regresión
        metrics=['accuracy', 'AUC']
    )
    
    return model

def prepare_sequences(data, sequence_length, target_col='target'):
    """
    Prepara secuencias para LSTM
    """
    X, y = [], []
    
    for i in range(sequence_length, len(data)):
        X.append(data.iloc[i-sequence_length:i].values)
        y.append(data[target_col].iloc[i])
    
    return np.array(X), np.array(y)

# Uso completo
def train_lstm_trading_model(prices, features, sequence_length=60):
    """
    Pipeline completo de entrenamiento LSTM
    """
    # Normalización
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)
    features_scaled = pd.DataFrame(features_scaled, index=features.index)
    
    # Crear secuencias
    X, y = prepare_sequences(features_scaled, sequence_length)
    
    # Split temporal
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    # Entrenar
    model = create_lstm_model(sequence_length, X.shape[2])
    
    callbacks = [
        tf.keras.callbacks.EarlyStopping(patience=10, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(factor=0.5, patience=5)
    ]
    
    history = model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=100,
        batch_size=32,
        callbacks=callbacks,
        verbose=1
    )
    
    return model, scaler, history
```

**Parámetros Típicos:**
- sequence_length: 20-252 días (1 mes - 1 año)
- LSTM units: 32-128
- Dropout: 0.2-0.5
- Learning rate: 0.001-0.0001

**Referencias:**
- Fischer, T.G. & Krauss, C. (2018). "Deep Learning with Long Short-Term Memory Networks for Financial Market Predictions" *European Journal of Operational Research*
- Nelson, D.M.Q. et al. (2017). "Stock Market's Price Movement Prediction with LSTM Neural Networks"

---

### 3.4 Reinforcement Learning (Q-Learning, PPO)

**Descripción:**
El agente aprende una política óptima de trading interactuando con el mercado, maximizando recompensas acumuladas.

**Componentes del Environment:**
```python
class TradingEnvironment:
    """
    Environment para RL de trading
    """
    def __init__(self, prices, features, initial_balance=10000):
        self.prices = prices
        self.features = features
        self.initial_balance = initial_balance
        self.reset()
    
    def reset(self):
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0  # 0: sin posición, 1: long
        self.portfolio_value = self.initial_balance
        return self._get_observation()
    
    def step(self, action):
        # Actions: 0 = hold, 1 = buy, 2 = sell
        current_price = self.prices.iloc[self.current_step]
        
        if action == 1 and self.position == 0:  # Buy
            self.position = 1
            self.entry_price = current_price
        elif action == 2 and self.position == 1:  # Sell
            pnl = (current_price - self.entry_price) / self.entry_price
            self.balance *= (1 + pnl)
            self.position = 0
        
        # Calcular portfolio value
        if self.position == 1:
            self.portfolio_value = self.balance * (current_price / self.entry_price)
        else:
            self.portfolio_value = self.balance
        
        # Reward: cambio en portfolio value
        reward = self.portfolio_value - self.initial_balance
        
        self.current_step += 1
        done = self.current_step >= len(self.prices) - 1
        
        return self._get_observation(), reward, done, {}
    
    def _get_observation(self):
        return self.features.iloc[self.current_step].values
```

**Implementación DQN (Deep Q-Network):**
```python
import torch
import torch.nn as nn
import torch.optim as optim
import random
from collections import deque

class DQN(nn.Module):
    def __init__(self, state_size, action_size):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(state_size, 128)
        self.fc2 = nn.Linear(128, 128)
        self.fc3 = nn.Linear(128, action_size)
        self.relu = nn.ReLU()
    
    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        return self.fc3(x)

class DQNAgent:
    def __init__(self, state_size, action_size):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=10000)
        self.gamma = 0.95  # discount factor
        self.epsilon = 1.0  # exploration rate
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.995
        self.learning_rate = 0.001
        
        self.model = DQN(state_size, action_size)
        self.target_model = DQN(state_size, action_size)
        self.optimizer = optim.Adam(self.model.parameters(), lr=self.learning_rate)
        self.criterion = nn.MSELoss()
    
    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))
    
    def act(self, state):
        if random.random() <= self.epsilon:
            return random.randrange(self.action_size)
        
        state = torch.FloatTensor(state).unsqueeze(0)
        q_values = self.model(state)
        return torch.argmax(q_values).item()
    
    def replay(self, batch_size=32):
        if len(self.memory) < batch_size:
            return
        
        batch = random.sample(self.memory, batch_size)
        states = torch.FloatTensor([e[0] for e in batch])
        actions = torch.LongTensor([e[1] for e in batch])
        rewards = torch.FloatTensor([e[2] for e in batch])
        next_states = torch.FloatTensor([e[3] for e in batch])
        dones = torch.FloatTensor([e[4] for e in batch])
        
        current_q = self.model(states).gather(1, actions.unsqueeze(1))
        next_q = self.target_model(next_states).max(1)[0].detach()
        target_q = rewards + (1 - dones) * self.gamma * next_q
        
        loss = self.criterion(current_q.squeeze(), target_q)
        
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
```

**Implementación PPO (Proximal Policy Optimization):**
```python
import torch
import torch.nn as nn
from torch.distributions import Categorical

class ActorCritic(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(ActorCritic, self).__init__()
        
        # Shared layers
        self.shared = nn.Sequential(
            nn.Linear(state_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 256),
            nn.ReLU()
        )
        
        # Actor (policy)
        self.actor = nn.Linear(256, action_dim)
        
        # Critic (value)
        self.critic = nn.Linear(256, 1)
    
    def forward(self, state):
        x = self.shared(state)
        action_probs = torch.softmax(self.actor(x), dim=-1)
        value = self.critic(x)
        return action_probs, value

class PPOAgent:
    def __init__(self, state_dim, action_dim, lr=3e-4, gamma=0.99, 
                 epsilon=0.2, epochs=10):
        self.gamma = gamma
        self.epsilon = epsilon
        self.epochs = epochs
        
        self.policy = ActorCritic(state_dim, action_dim)
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=lr)
    
    def select_action(self, state):
        state = torch.FloatTensor(state)
        action_probs, value = self.policy(state)
        dist = Categorical(action_probs)
        action = dist.sample()
        return action.item(), dist.log_prob(action), value
    
    def compute_returns(self, rewards, dones, values):
        returns = []
        R = 0
        for reward, done, value in zip(reversed(rewards), reversed(dones), reversed(values)):
            if done:
                R = 0
            R = reward + self.gamma * R
            returns.insert(0, R)
        return torch.FloatTensor(returns)
    
    def update(self, states, actions, log_probs, returns, advantages):
        for _ in range(self.epochs):
            action_probs, values = self.policy(states)
            dist = Categorical(action_probs)
            
            new_log_probs = dist.log_prob(actions)
            ratio = torch.exp(new_log_probs - log_probs)
            
            surr1 = ratio * advantages
            surr2 = torch.clamp(ratio, 1 - self.epsilon, 1 + self.epsilon) * advantages
            actor_loss = -torch.min(surr1, surr2).mean()
            
            critic_loss = nn.MSELoss()(values.squeeze(), returns)
            
            loss = actor_loss + 0.5 * critic_loss - 0.01 * dist.entropy().mean()
            
            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()
```

**Referencias:**
- Jiang, Z., Xu, D. & Liang, J. (2017). "A Deep Reinforcement Learning Framework for the Financial Portfolio Management Problem" *arXiv:1706.10059*
- Sadighian, J. (2020). "Extending Deep Reinforcement Learning Frameworks in Cryptocurrency Market Making" *arXiv:2004.06985*

---

## 4. ESTRATEGIAS DE RISK PARITY

### 4.1 Risk Parity Básico

**Descripción:**
Asigna capital de forma que cada activo contribuya igualmente al riesgo total del portafolio, en lugar de asignar capital igual.

**Fórmula:**
```
Risk Contribution_i = w_i * (Σw)_i / σ_p

Donde:
- w_i = peso del activo i
- Σ = matriz de covarianza
- (Σw)_i = i-ésimo elemento del vector Σw
- σ_p = volatilidad del portafolio = sqrt(w'Σw)

Objetivo: RC_i = RC_j para todo i,j
```

**Implementación:**
```python
import numpy as np
from scipy.optimize import minimize

def risk_parity_weights(returns):
    """
    Calcula pesos de Risk Parity
    returns: DataFrame de retornos históricos
    """
    cov = returns.cov().values
    n_assets = len(returns.columns)
    
    def portfolio_volatility(weights):
        return np.sqrt(weights @ cov @ weights)
    
    def risk_contribution(weights):
        port_vol = portfolio_volatility(weights)
        marginal_risk = (cov @ weights) / port_vol
        risk_contrib = weights * marginal_risk
        return risk_contrib
    
    # Función objetivo: minimizar diferencia entre risk contributions
    def objective(weights):
        rc = risk_contribution(weights)
        target_rc = port_vol / n_assets  # Risk contribution objetivo
        return np.sum((rc - target_rc) ** 2)
    
    # Restricciones
    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},  # Suma de pesos = 1
        {'type': 'ineq', 'fun': lambda w: w}  # Pesos >= 0
    ]
    
    # Optimización
    initial_weights = np.ones(n_assets) / n_assets
    result = minimize(objective, initial_weights, 
                     method='SLSQP', constraints=constraints)
    
    return pd.Series(result.x, index=returns.columns)
```

**Referencias:**
- Qian, E. (2005). "Risk Parity Portfolios: Efficient Portfolios Through True Diversification"
- Maillard, S., Roncalli, T. & Teïletche, J. (2010). "The Properties of Equally Weighted Risk Contribution Portfolios" *Journal of Portfolio Management*

---

### 4.2 Inverse Volatility

**Descripción:**
Versión simplificada de Risk Parity que asume correlaciones cero entre activos. Peso inversamente proporcional a la volatilidad.

**Fórmula:**
```
w_i = (1/σ_i) / Σ(1/σ_j)
```

**Implementación:**
```python
def inverse_volatility_weights(returns, lookback=252):
    """
    Pesos inversamente proporcionales a la volatilidad
    """
    volatility = returns.iloc[-lookback:].std() * np.sqrt(252)
    inv_vol = 1 / volatility
    weights = inv_vol / inv_vol.sum()
    return weights
```

---

### 4.3 Maximum Diversification

**Descripción:**
Maximiza el ratio de diversificación, definido como la suma ponderada de volatilidades individuales dividida por la volatilidad del portafolio.

**Fórmula:**
```
Maximizar: D(w) = (w'σ) / sqrt(w'Σw)

Donde σ es el vector de desviaciones estándar individuales
```

**Implementación:**
```python
def maximum_diversification_weights(returns):
    """
    Maximum Diversification Portfolio
    """
    cov = returns.cov().values
    vols = returns.std().values
    n = len(vols)
    
    def diversification_ratio(weights):
        port_vol = np.sqrt(weights @ cov @ weights)
        weighted_vols = np.sum(weights * vols)
        return -weighted_vols / port_vol  # Negativo para minimizar
    
    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'ineq', 'fun': lambda w: w}
    ]
    
    initial = np.ones(n) / n
    result = minimize(diversification_ratio, initial, 
                     method='SLSQP', constraints=constraints)
    
    return pd.Series(result.x, index=returns.columns)
```

**Referencias:**
- Choueifaty, Y. & Coignard, Y. (2008). "Toward Maximum Diversification" *Journal of Portfolio Management*

---

### 4.4 Minimum Variance Portfolio

**Descripción:**
Portafolio con la mínima volatilidad posible dada la matriz de covarianza.

**Fórmula:**
```
Minimizar: σ_p² = w'Σw
Sujeto a: Σw_i = 1
```

**Implementación:**
```python
def minimum_variance_weights(returns):
    """
    Minimum Variance Portfolio
    """
    cov = returns.cov().values
    n = cov.shape[0]
    
    def portfolio_variance(weights):
        return weights @ cov @ weights
    
    constraints = [
        {'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
        {'type': 'ineq', 'fun': lambda w: w}
    ]
    
    initial = np.ones(n) / n
    result = minimize(portfolio_variance, initial,
                     method='SLSQP', constraints=constraints)
    
    return pd.Series(result.x, index=returns.columns)
```

---

## 5. ESTRATEGIAS DE MEAN REVERSION

### 5.1 Pairs Trading

**Descripción:**
Estrategia market-neutral que explota la relación de cointegración entre dos activos. Cuando el spread se desvía de la media histórica, se toma posición esperando reversión.

**Fórmula/Lógica:**
```
Spread = Precio_A - β * Precio_B
Z-Score = (Spread - Media_Spread) / StdDev_Spread

Señales:
- Z-Score > 2: Short A, Long B (spread alto, espera baje)
- Z-Score < -2: Long A, Short B (spread bajo, espera suba)
- |Z-Score| < 0.5: Cerrar posición
```

**Implementación:**
```python
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

def find_cointegrated_pairs(prices):
    """
    Encuentra pares cointegrados
    """
    n = prices.shape[1]
    score_matrix = np.zeros((n, n))
    pvalue_matrix = np.ones((n, n))
    keys = prices.columns
    pairs = []
    
    for i in range(n):
        for j in range(i+1, n):
            S1 = prices.iloc[:, i]
            S2 = prices.iloc[:, j]
            result = coint(S1, S2)
            score = result[0]
            pvalue = result[1]
            score_matrix[i, j] = score
            pvalue_matrix[i, j] = pvalue
            if pvalue < 0.05:
                pairs.append((keys[i], keys[j], pvalue))
    
    return pairs, pvalue_matrix

def calculate_hedge_ratio(S1, S2):
    """
    Calcula el hedge ratio por regresión OLS
    """
    S1 = sm.add_constant(S1)
    model = sm.OLS(S2, S1).fit()
    beta = model.params[1]
    return beta

def pairs_trading_signals(price_a, price_b, lookback=60, entry_z=2, exit_z=0.5):
    """
    Genera señales de pairs trading
    """
    # Calcular hedge ratio con ventana rodante
    hedge_ratio = calculate_hedge_ratio(
        price_a.iloc[-lookback:], 
        price_b.iloc[-lookback:]
    )
    
    # Calcular spread
    spread = price_a - hedge_ratio * price_b
    
    # Z-score del spread
    spread_mean = spread.rolling(lookback).mean()
    spread_std = spread.rolling(lookback).std()
    zscore = (spread - spread_mean) / spread_std
    
    # Generar señales
    current_z = zscore.iloc[-1]
    
    if current_z > entry_z:
        signal = -1  # Short spread
    elif current_z < -entry_z:
        signal = 1   # Long spread
    elif abs(current_z) < exit_z:
        signal = 0   # Cerrar posición
    else:
        signal = None  # Mantener
    
    return {
        'signal': signal,
        'zscore': current_z,
        'hedge_ratio': hedge_ratio,
        'spread': spread.iloc[-1]
    }
```

**Referencias:**
- Gatev, E., Goetzmann, W.N. & Rouwenhorst, K.G. (2006). "Pairs Trading: Performance of a Relative-Value Arbitrage Rule" *Review of Financial Studies*
- Vidyamurthy, G. (2004). *Pairs Trading: Quantitative Methods and Analysis*. Wiley

---

### 5.2 Statistical Arbitrage

**Descripción:**
Extensión de pairs trading a múltiples activos usando modelos de factor o cointegración multivariada.

**Implementación PCA-based:**
```python
from sklearn.decomposition import PCA

def statistical_arbitrage_pca(returns, n_components=5):
    """
    StatArb usando PCA para extraer factores
    """
    # Aplicar PCA a retornos
    pca = PCA(n_components=n_components)
    factors = pca.fit_transform(returns)
    
    # Reconstruir retornos esperados
    reconstructed = pca.inverse_transform(factors)
    
    # Residuos = alpha
    residuals = returns - reconstructed
    
    # Estrategia: Long activos con residuos negativos (subvalorados)
    #             Short activos con residuos positivos (sobrevalorados)
    signals = -np.sign(residuals.iloc[-1])  # Contrarian
    
    return signals, residuals, pca
```

---

### 5.3 Bollinger Bands Mean Reversion

**Descripción:**
Usa bandas de Bollinger para identificar condiciones de sobrecompra/sobreventa.

**Fórmula:**
```
Middle Band = SMA(20)
Upper Band = SMA(20) + 2 * StdDev(20)
Lower Band = SMA(20) - 2 * StdDev(20)

Señales:
- Precio > Upper Band → Short (sobrecompra)
- Precio < Lower Band → Long (sobreventa)
- Precio cruza Middle Band → Cerrar posición
```

**Implementación:**
```python
def bollinger_bands_signals(prices, window=20, num_std=2):
    """
    Señales de mean reversion con Bollinger Bands
    """
    sma = prices.rolling(window).mean()
    std = prices.rolling(window).std()
    
    upper_band = sma + num_std * std
    lower_band = sma - num_std * std
    
    current_price = prices.iloc[-1]
    
    if current_price > upper_band.iloc[-1]:
        signal = -1  # Short
    elif current_price < lower_band.iloc[-1]:
        signal = 1   # Long
    elif abs(current_price - sma.iloc[-1]) / sma.iloc[-1] < 0.01:
        signal = 0   # Cerrar (cerca de media)
    else:
        signal = None
    
    return {
        'signal': signal,
        'price': current_price,
        'upper': upper_band.iloc[-1],
        'lower': lower_band.iloc[-1],
        'sma': sma.iloc[-1]
    }
```

---

### 5.4 Ornstein-Uhlenbeck Process

**Descripción:**
Proceso estocástico mean-reverting usado para modelar spreads y optimizar entradas/salidas en pairs trading.

**Ecuación Diferencial Estocástica:**
```
dX(t) = θ(μ - X(t))dt + σdW(t)

Donde:
- θ: velocidad de reversión a la media
- μ: media de largo plazo
- σ: volatilidad
- dW(t): proceso de Wiener

Solución:
X(t) = X(0)e^(-θt) + μ(1 - e^(-θt)) + σ∫e^(-θ(t-s))dW(s)
```

**Implementación:**
```python
import numpy as np
from scipy.optimize import minimize

def fit_ornstein_uhlenbeck(spread):
    """
    Estima parámetros OU por máxima verosimilitud
    """
    n = len(spread)
    dt = 1/252  # Asumiendo datos diarios
    
    # Estimación por momentos como inicial
    diff = np.diff(spread)
    x = spread[:-1]
    
    # Regresión: dx = θ(μ - x)dt + σdW
    # => dx = θμdt - θx dt + σdW
    # => dx/dt = a + b*x, donde a = θμ, b = -θ
    
    slope, intercept = np.polyfit(x, diff, 1)
    
    theta = -slope / dt
    mu = intercept / (slope * dt)
    sigma = np.std(diff - slope * x - intercept) / np.sqrt(dt)
    
    return {'theta': theta, 'mu': mu, 'sigma': sigma}

def ou_half_life(theta):
    """
    Tiempo de half-life del proceso OU
    """
    return np.log(2) / theta

def optimal_entry_exit_ou(mu, theta, sigma, transaction_cost=0.001):
    """
    Calcula niveles óptimos de entrada/salida basados en OU
    Basado en Bertram (2010)
    """
    # Simplificación: usar múltiplos de sigma
    entry_level = mu + 1.5 * sigma / np.sqrt(2 * theta)
    exit_level = mu
    stop_loss = mu + 3 * sigma / np.sqrt(2 * theta)
    
    return {
        'entry_long': mu - (entry_level - mu),
        'entry_short': entry_level,
        'exit_long': exit_level,
        'exit_short': exit_level,
        'stop_loss': stop_loss,
        'half_life': ou_half_life(theta)
    }

def simulate_ou_process(theta, mu, sigma, x0, T, dt=1/252):
    """
    Simula trayectorias del proceso OU
    """
    n_steps = int(T / dt)
    x = np.zeros(n_steps)
    x[0] = x0
    
    for t in range(1, n_steps):
        dx = theta * (mu - x[t-1]) * dt + sigma * np.sqrt(dt) * np.random.normal()
        x[t] = x[t-1] + dx
    
    return x
```

**Referencias:**
- Leung, T. & Li, X. (2015). "Optimal Mean Reversion Trading with Transaction Costs and Stop-Loss Exit" *International Journal of Theoretical and Applied Finance*
- Bertram, W.K. (2010). "Optimal Trading Strategies for Itô Processes" *Physica A*

---

## 6. ESTRATEGIAS DE TREND FOLLOWING

### 6.1 Donchian Channels

**Descripción:**
Canales basados en máximos y mínimos de n períodos. Señal de compra cuando el precio rompe el máximo, venta cuando rompe el mínimo.

**Fórmula:**
```
Upper Channel = Max(High, n períodos)
Lower Channel = Min(Low, n períodos)
Middle Channel = (Upper + Lower) / 2

Señales:
- Close > Upper Channel → Long
- Close < Lower Channel → Short/Exit
```

**Implementación:**
```python
def donchian_channels(df, period=20):
    """
    Donchian Channels
    df: DataFrame con columnas ['high', 'low', 'close']
    """
    upper = df['high'].rolling(window=period).max()
    lower = df['low'].rolling(window=period).min()
    middle = (upper + lower) / 2
    
    return pd.DataFrame({
        'upper': upper,
        'middle': middle,
        'lower': lower
    })

def donchian_signals(df, entry_period=20, exit_period=10):
    """
    Señales de Donchian Channel
    """
    entry_channels = donchian_channels(df, entry_period)
    exit_channels = donchian_channels(df, exit_period)
    
    close = df['close']
    
    # Señales
    long_entry = close > entry_channels['upper'].shift(1)
    long_exit = close < exit_channels['lower'].shift(1)
    
    short_entry = close < entry_channels['lower'].shift(1)
    short_exit = close > exit_channels['upper'].shift(1)
    
    return pd.DataFrame({
        'long_entry': long_entry,
        'long_exit': long_exit,
        'short_entry': short_entry,
        'short_exit': short_exit
    })
```

---

### 6.2 Turtle Trading

**Descripción:**
Sistema de trading mecánico desarrollado por Richard Dennis. Usa breakouts de N períodos con filtros de volatilidad (ATR).

**Reglas del Sistema:**
```
Entry:
- Long cuando precio > Max(High, 20 días)
- Short cuando precio < Min(Low, 20 días)

Exit:
- Long exit cuando precio < Min(Low, 10 días)
- Short exit cuando precio > Max(High, 10 días)

Position Sizing:
- Unit = (Account * 0.01) / (N * Price per point)
- Donde N = 20-day ATR
- Max 4 units por dirección
- Stop loss a 2N del entry
```

**Implementación:**
```python
def turtle_trading_system(df, account_size=100000):
    """
    Sistema Turtle Trading completo
    df: DataFrame con ['high', 'low', 'close']
    """
    # Calcular N (20-day ATR)
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    n = tr.rolling(20).mean()
    
    # Canales Donchian
    entry_upper = df['high'].rolling(20).max()
    entry_lower = df['low'].rolling(20).min()
    exit_upper = df['high'].rolling(10).max()
    exit_lower = df['low'].rolling(10).min()
    
    # Señales
    long_signal = df['close'] > entry_upper.shift(1)
    short_signal = df['close'] < entry_lower.shift(1)
    exit_long = df['close'] < exit_lower.shift(1)
    exit_short = df['close'] > exit_upper.shift(1)
    
    # Position sizing
    dollar_risk = account_size * 0.01
    position_size = dollar_risk / (n * df['close'])
    
    return pd.DataFrame({
        'n': n,
        'long_signal': long_signal,
        'short_signal': short_signal,
        'exit_long': exit_long,
        'exit_short': exit_short,
        'position_size': position_size,
        'stop_loss_long': df['close'] - 2 * n,
        'stop_loss_short': df['close'] + 2 * n
    })
```

**Referencias:**
- Faith, C. (2007). *Way of the Turtle*. McGraw-Hill
- Covel, M.W. (2009). *The Complete Turtle Trader*. HarperBusiness

---

### 6.3 Moving Average Crossovers Avanzados

**Descripción:**
Estrategias que combinan múltiples MAs con filtros de tendencia y confirmación.

**Variantes:**
```python
def triple_ma_system(prices, fast=10, medium=30, slow=50):
    """
    Sistema de Triple Moving Average
    """
    ma_fast = prices.rolling(fast).mean()
    ma_medium = prices.rolling(medium).mean()
    ma_slow = prices.rolling(slow).mean()
    
    # Tendencia alcista: fast > medium > slow
    uptrend = (ma_fast > ma_medium) & (ma_medium > ma_slow)
    
    # Señal de entrada cuando fast cruza above medium en tendencia alcista
    entry = (ma_fast > ma_medium) & (ma_fast.shift(1) <= ma_medium.shift(1)) & uptrend
    
    # Salida cuando fast cruza below medium
    exit_signal = (ma_fast < ma_medium) & (ma_fast.shift(1) >= ma_medium.shift(1))
    
    return pd.DataFrame({
        'ma_fast': ma_fast,
        'ma_medium': ma_medium,
        'ma_slow': ma_slow,
        'uptrend': uptrend,
        'entry': entry,
        'exit': exit_signal
    })

def macd_enhanced(prices, fast=12, slow=26, signal=9):
    """
    MACD con histograma y señales de divergencia
    """
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    
    # Señales
    bullish_cross = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    bearish_cross = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
    
    # Divergencias (simplificado)
    price_higher_high = (prices > prices.rolling(20).max().shift(1))
    macd_lower_high = (macd_line < macd_line.rolling(20).max().shift(1))
    bearish_divergence = price_higher_high & macd_lower_high
    
    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram,
        'bullish_cross': bullish_cross,
        'bearish_cross': bearish_cross,
        'bearish_divergence': bearish_divergence
    })
```

---

### 6.4 Keltner Channels

**Descripción:**
Canales basados en ATR en lugar de desviación estándar, más adaptativos a la volatilidad.

**Fórmula:**
```
Middle Line = EMA(20)
Upper Channel = EMA(20) + 2 * ATR(10)
Lower Channel = EMA(20) - 2 * ATR(10)

Señales:
- Breakout above upper → Señal de compra fuerte (trend continuation)
- Breakout below lower → Señal de venta fuerte
- Reversión a la media cuando toca bandas
```

**Implementación:**
```python
def keltner_channels(df, ema_period=20, atr_period=10, multiplier=2):
    """
    Keltner Channels
    df: DataFrame con ['high', 'low', 'close']
    """
    # EMA del typical price
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    middle = typical_price.ewm(span=ema_period).mean()
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    
    upper = middle + multiplier * atr
    lower = middle - multiplier * atr
    
    return pd.DataFrame({
        'upper': upper,
        'middle': middle,
        'lower': lower,
        'atr': atr
    })

def keltner_signals(df, ema_period=20, atr_period=10):
    """
    Señales de Keltner Channels
    """
    kc = keltner_channels(df, ema_period, atr_period)
    close = df['close']
    
    # Señales de trend following
    strong_buy = close > kc['upper']
    strong_sell = close < kc['lower']
    
    # Señales de mean reversion (dentro del canal)
    near_upper = (close > kc['upper'] * 0.995) & (close <= kc['upper'])
    near_lower = (close < kc['lower'] * 1.005) & (close >= kc['lower'])
    
    return pd.DataFrame({
        'strong_buy': strong_buy,
        'strong_sell': strong_sell,
        'near_upper': near_upper,
        'near_lower': near_lower,
        'position_in_channel': (close - kc['lower']) / (kc['upper'] - kc['lower'])
    })
```

---

## REFERENCIAS GENERALES Y LIBROS RECOMENDADOS

### Papers Fundamentales:
1. **Fama & French (1993)** - "Common Risk Factors in the Returns on Stocks and Bonds"
2. **Moskowitz & Grinblatt (1999)** - "Do Industries Explain Momentum?"
3. **Asness (1997)** - "The Interaction of Value and Momentum Strategies"
4. **Gu, Kelly & Xiu (2020)** - "Empirical Asset Pricing via Machine Learning"
5. **Hurst, Ooi & Pedersen (2013)** - "Demystifying Managed Futures"

### Libros Esenciales:
1. **Antonacci, G.** - *Dual Momentum Investing* (2014)
2. **Chan, E.** - *Quantitative Trading* (2009)
3. **Chan, E.** - *Algorithmic Trading* (2013)
4. **Lopez de Prado, M.** - *Advances in Financial Machine Learning* (2018)
5. **Grinold & Kahn** - *Active Portfolio Management* (1999)
6. **Vidyamurthy, G.** - *Pairs Trading* (2004)
7. **Covel, M.** - *Trend Following* (2009)

### Recursos Online:
- SSRN (Social Science Research Network)
- arXiv (q-fin.CP - Computational Finance)
- Journal of Financial Economics
- Review of Financial Studies
- AQR Insights (aqr.com)

---

## NOTAS DE IMPLEMENTACIÓN

### Consideraciones Importantes:

1. **Look-ahead Bias**: Asegurar que solo se use información disponible en el momento del trade
2. **Transaction Costs**: Siempre incluir comisiones y slippage en backtests
3. **Survivorship Bias**: Usar datos que incluyan empresas que dejaron de cotizar
4. **Overfitting**: Validar con walk-forward analysis, no solo backtest simple
5. **Regime Changes**: Los mercados cambian, lo que funcionó antes puede no funcionar después

### Framework de Backtesting Recomendado:
```python
# Estructura típica de backtest

def backtest_strategy(prices, strategy_func, **kwargs):
    results = []
    
    for date in date_range:
        # Solo usar datos hasta 'date'
        historical_data = prices.loc[:date]
        
        # Generar señales
        signal = strategy_func(historical_data, **kwargs)
        
        # Ejecutar con slippage y comisiones
        execution_price = get_execution_price(date, signal)
        
        # Trackear P&L
        results.append(calculate_pnl(signal, execution_price))
    
    return analyze_results(results)
```

---

*Documento generado para integración en sistema de trading*
*Fecha: Febrero 2026*
