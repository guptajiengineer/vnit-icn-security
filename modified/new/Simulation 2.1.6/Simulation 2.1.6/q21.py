import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import Lasso

x = np.array([1,1.5,2,2.5,3]).reshape((-1, 1))
y = np.array([12, 15, 18, 20, 23])

# Fit Lasso regression model with alpha=1 (lambda)
model = Lasso(alpha=1).fit(x, y)

# Predict sales for temperature = 28
expected_sales = model.predict(np.array([2.2]).reshape((-1, 1)))
print(expected_sales)

# Scatter plot of data points
plt.scatter(x, y, color='blue')

# Plot regression line
x_line = np.linspace(x.min(), x.max(), 100).reshape(-1, 1)  # smooth range for x
y_line = model.predict(x_line)  # predicted y values from model
plt.plot(x_line, y_line, color='red')

plt.xlabel('ad spend(lakhs)')
plt.ylabel('sales(lakhs)')
plt.title('Lasso Regression Fit (alpha=1)')
plt.show()
