import numpy as np
import matplotlib.pyplot as plt
import io

# Define the asset parameters based on user's option C
# Ratios: 40% DCDS, 30% DCDE, 20% ETFVN30, 10% CCQ
ASSETS = {
    "DCDS": {"return_annual": 0.28, "volatility_annual": 0.15, "ratio": 0.40},
    "DCDE": {"return_annual": 0.22, "volatility_annual": 0.18, "ratio": 0.30},
    "ETFVN30": {"return_annual": 0.18, "volatility_annual": 0.12, "ratio": 0.20},
    "CCQ": {"return_annual": 0.075, "volatility_annual": 0.00, "ratio": 0.10},
}

def run_monte_carlo(current_portfolio_value, monthly_contribution, months=60, num_simulations=1000):
    """
    Runs a Monte Carlo simulation for the portfolio.
    Returns the paths of the total portfolio value.
    """
    # Initialize array to store paths: shape (num_simulations, months + 1)
    paths = np.zeros((num_simulations, months + 1))
    paths[:, 0] = current_portfolio_value

    # Start tracking each asset
    asset_values = np.zeros((num_simulations, len(ASSETS)))
    
    # Initialize starting values based on target ratios
    for idx, (name, params) in enumerate(ASSETS.items()):
        asset_values[:, idx] = current_portfolio_value * params["ratio"]

    # Pre-calculate monthly params
    monthly_params = []
    for name, params in ASSETS.items():
        monthly_return = params["return_annual"] / 12
        monthly_volatility = params["volatility_annual"] / np.sqrt(12)
        monthly_params.append((monthly_return, monthly_volatility, params["ratio"]))

    # Simulate month by month
    for month in range(1, months + 1):
        for idx, (m_ret, m_vol, ratio) in enumerate(monthly_params):
            # Generate random monthly returns for this asset
            random_returns = np.random.normal(m_ret, m_vol, num_simulations)
            
            # Update asset value: apply return, then add new contribution
            asset_values[:, idx] = asset_values[:, idx] * (1 + random_returns) + (monthly_contribution * ratio)
            
        # Sum all assets for the total portfolio value this month
        paths[:, month] = np.sum(asset_values, axis=1)

    return paths

def generate_projection_chart(paths, monthly_contribution):
    """
    Generates a matplotlib chart from the simulation paths and returns it as a BytesIO stream.
    """
    months = paths.shape[1] - 1
    x = np.arange(months + 1)
    
    # Calculate statistics
    median_path = np.median(paths, axis=0)
    p10_path = np.percentile(paths, 10, axis=0)
    p90_path = np.percentile(paths, 90, axis=0)
    
    # Calculate total capital invested baseline
    initial_value = paths[0, 0]
    capital_path = initial_value + (x * monthly_contribution)

    plt.figure(figsize=(10, 6))
    
    # Plot a sample of individual paths (light and transparent)
    num_samples = min(50, paths.shape[0])
    for i in range(num_samples):
        plt.plot(x, paths[i, :], color='blue', alpha=0.05)

    # Plot percentiles and median
    plt.fill_between(x, p10_path, p90_path, color='blue', alpha=0.2, label='10th-90th Percentile')
    plt.plot(x, median_path, color='blue', linewidth=2, label='Median Projection')
    
    # Plot capital invested
    plt.plot(x, capital_path, color='red', linestyle='--', linewidth=2, label='Total Capital Invested')

    # Formatting
    plt.title(f"{months}-Month Portfolio Projection (Monte Carlo)", fontsize=14)
    plt.xlabel("Months", fontsize=12)
    plt.ylabel("Portfolio Value (VND)", fontsize=12)
    
    # Format y-axis as millions/billions
    def currency_formatter(x, pos):
        if x >= 1e9:
            return f'{x*1e-9:.1f}B'
        elif x >= 1e6:
            return f'{x*1e-6:.0f}M'
        return f'{x:,.0f}'
    
    plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(currency_formatter))
    plt.grid(True, linestyle=':', alpha=0.7)
    plt.legend(loc='upper left')
    plt.tight_layout()

    # Save to BytesIO
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100)
    plt.close()
    buf.seek(0)
    
    # Also return final stats
    stats = {
        "median": median_path[-1],
        "p10": p10_path[-1],
        "p90": p90_path[-1],
        "capital": capital_path[-1]
    }
    
    return buf, stats
