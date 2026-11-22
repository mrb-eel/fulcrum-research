import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
checks = []


def check(label, actual, expected, tol=1e-6):
    assert abs(actual - expected) <= tol, (label, actual, expected)
    checks.append({"calculation": label, "value": actual, "expected": expected})


check("Loan terminal recovery", 1_000_000 * 0.7 * 0.95, 665000)
check("Loan terminal shortfall", 750000 - 1_000_000 * 0.7 * 0.95, 85000)
check("Liquidation distance", 1 - 750000 / (1000000 * 0.86), 0.12790697674418605)
lif = 1 / (0.3 * 0.86 + 0.7)
check("LIF at 86 percent LLTV", lif, 1.0438413361169103)
check("Liquidation break-even discount", 1 - 1 / lif, 0.042)
check("Four percent discount margin", lif * 0.96 - 1, 0.002087682672233803)
check("Constant product 20 percent sale discount", 1 - 1 / 1.2, 1 / 6)
check(
    "Constant product relative LP return at fourfold price",
    2 * math.sqrt(4) / 5 - 1,
    -0.2,
)
check("Thirty-day opportunity cost", 1_000_000 * 0.04 * 30 / 365, 3287.671232876712)
exit_cost = 2500 + 200 + 1_000_000 * 0.04 * 30 / 365
check("Incremental exit cost", exit_cost, 5987.671232876712)
check("Exit threshold", exit_cost / 140000, 0.04276908023483366)
check(
    "Reverse stress with one percent execution discount",
    1 - 0.975 / 0.99,
    0.015151515151515138,
)
check("Market A borrower A1 severe shortfall", 4e6 - 6e6 * 0.7 * 0.95, 10000)
check("Market A borrower A2 severe shortfall", 3e6 - 3.6e6 * 0.7 * 0.95, 606000)
check("Market A severe total", 10000 + 606000, 616000)
check("Vault severe loss", 616000 * 0.2, 123200)
check("Holder severe loss", 616000 * 0.2 * 0.2, 24640)
check("Market A moderate shortfall", 3e6 - 3.6e6 * 0.8 * 0.95, 264000)
check("Holder moderate shortfall", 264000 * 0.2 * 0.2, 10560)
new_loss = 3e6 - (3e6 / 0.86) * 0.7 * 0.95
check("Stale-price new borrower shortfall", new_loss, 680232.5581395351)
check("Combined holder loss", (616000 + new_loss) * 0.2 * 0.2, 51849.302325581404)
check("Partial withdrawal break-even", 3000 / 12320, 0.2435064935064935)
check("Financed initial health", 1e6 * 0.915 / 850000, 1.076470588235294)
check("Stressed equity", 1e6 * 0.98 * 0.97 - 850000, 100600)
check("Reference equity loss", 49400 / 150000, 0.3293333333333333)
check("Executable baseline loss", 39400 / 140000, 0.2814285714285714)
check("Partial debt", 850000 - 297000, 553000)
check("Residual health", 700000 * 0.915 / 553000, 1.1582278481012658)
check("Withdrawable without repayment", 1e6 - 850000 / 0.915, 71038.2513661203)
check("Intermediate debt capacity", 700000 * 0.915, 640500)
check("Intermediate safety margin", 640500 - 640000, 500)
check("Residual event equity", 700000 * 0.98 * 0.97 - 553000, 112420)
check("Final event outcome improvement", 49400 - 37580, 11820)
check("Incremental event loss avoided", 49400 - 34580, 14820)
check("Correct partial action threshold", 3000 / 14820, 0.20242914979757085)
check("Glossary exercise health", 2e6 * 0.86 / 1.5e6, 1.1466666666666667)
check("Liquidation exercise gross margin", (0.975 / 0.97 - 1) * 100, 0.5154639175257718)
check("Fourteen day financing interest", 250000 * 0.12 * 14 / 365, 1150.6849315068494)
check("PT rounded equity amplification", 39340 / 520000, 0.07565384615384615)
check("Relative collateral decline with loan depeg", 1 - 0.8 / 0.95, 0.1578947368421052)
check(
    "Loop collateral after five reinvestments",
    100000 * sum(0.8**k for k in range(6)),
    368928,
)
pa = 58 / 0.68
pb = 20 + 0.8 * pa
check("Clearing A payment", pa, 85.29411764705881)
check("Clearing B payment", pb, 88.23529411764706)
check("Outside clearing receipts", 0.2 * pa + 0.6 * pb, 70)
check("Gross liquidation capacity", 1e6 * (1 - 1 / lif), 42000)
check(
    "Binomial zero events upper confidence limit",
    1 - 0.05 ** (1 / 20),
    0.13910834066826516,
)
check("Uniform-prior posterior mean", 1 / 22, 0.045454545454545456)
check("Uniform-prior posterior upper limit", 1 - 0.05 ** (1 / 21), 0.13294591102652343)
check("Joint event independent union", 1 - 0.96 * 0.97, 0.0688)
check("Positive threshold interaction", 90 - 100 * 0.92 * 0.96, 1.68)
check("Unknown debt holder upper loss", 500000 * 0.2 * 0.1, 10000)
f = (0.1 * 100000 - 2000) / (2 * 18000)
check("Optimal partial reduction", f, 2 / 9)
cost = 2000 * f + 18000 * f * f + 300 + 10000 * (1 - f)
check("Optimal partial expected cost", cost, 9411.111111111111)
check("Partial action expected saving", 10000 - cost, 588.8888888888887)
check(
    "Partial action activation probability",
    (2000 + 2 * math.sqrt(18000 * 300)) / 100000,
    0.066475800154489,
)
check("Partial action jump size", math.sqrt(300 / 18000), 0.12909944487358055)
x = 1000 * (1 / 10 - 1 / 11)
y = 1000 * (10 - 9)
check("Concentrated LP initial x", x, 9.090909090909093)
check("Concentrated LP initial y", y, 1000)
check("Concentrated LP initial value", 100 * x + y, 1909.0909090909095)
check("Concentrated LP upper holding benchmark", 121 * x + y, 2100)
check("Concentrated LP upper relative return", 2000 / 2100 - 1, -0.04761904761904767)
check("Concentrated LP lower inventory", 1000 * (1 / 9 - 1 / 11), 20.20202020202019)
check("PT implied annual yield", (1 / 0.96) ** 2 - 1, 0.08506944444444464)
repay = 0.85 * math.sqrt(1.10)
check("Financed PT terminal equity", 1 - repay, 0.10851247906137118)
check("Financed PT equity return", (1 - repay) / 0.11 - 1, -0.013522917623898456)
check("Recovery financing first period", 400000 * 0.12 * 7 / 365, 920.5479452054794)
check("Recovery financing second period", 100000 * 0.12 * 16 / 365, 526.0273972602739)
check(
    "Recovery total financing cost",
    400000 * 0.12 * 7 / 365 + 100000 * 0.12 * 16 / 365,
    1446.5753424657532,
)
check("Required temporary financing", 850000 - 0.915 * (1e6 - 300000), 209500)
check("Financing fee", 230000 * 0.0009, 207)
check("Fee-adjusted remaining debt", 850000 - 297000 + 207, 553207)
