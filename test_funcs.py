import os
import numpy as np
import matplotlib.pyplot as plt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def plot_func(x, y, file_name="plot.png"):
    fig, ax = plt.subplots()
    ax.axhline(y=0, color="k")
    ax.axvline(x=0, color="k")
    ax.grid(True)
    ax.plot(x, y)

    file_path = os.path.join(BASE_DIR, file_name)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    fig.savefig(file_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# Plotting Linear Polynomial func
x = np.linspace(-5, 5, 100)
y = 0.5 * x + 1
plot_func(x, y, "plot1.png")

# Plotting Quadratic funcs
x = np.linspace(-2, 2, 100)
y = -0.5 * 9.8 * x ** 2 + 2 * x + 1
plot_func(x, y, "plot2.png")

x = np.linspace(0, 10, 100)
y = -0.5 * x ** (1 / 3) + 0.2 * x ** (1 / 2) + 1
plot_func(x, y, "plot3.png")

# Plotting Cubic Polynomial func
x = np.linspace(-3, 3, 100)
y = 0.1 * x ** 3 - 0.5 * x ** 2 + x - 2
plot_func(x, y, "plot_poly4.png")

# Plotting Exponential funcs
x = np.linspace(-5, 5, 100)
y = np.e ** x  # This is the same the magic number 'e' raised to the power of x
plot_func(x, y, "plot4.png")

# Additional Exponential func (base 2)
x = np.linspace(-5, 5, 100)
y = 2 ** x  # exponential with base 2
plot_func(x, y, "plot5.png")

print("hhuhuhuhahhahhah")
