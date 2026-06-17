import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import Lasso

x = np.array([1,2,3,4,5]).reshape((-1, 1))
y = np.array([6.5,5.9,5.2,4.6,4.0])

# Fit Lasso regression model with alpha=1 (lambda)
model = Lasso(alpha=0.5).fit(x, y)

expected_sales = model.predict(np.array([3.5]).reshape((-1, 1)))
print(expected_sales)

# Scatter plot of data points
plt.scatter(x, y, color='blue')

# Plot regression line
x_line = np.linspace(x.min(), x.max(), 100).reshape(-1, 1)  # smooth range for x
y_line = model.predict(x_line)  # predicted y values from model
plt.plot(x_line, y_line, color='red')

plt.xlabel('car age (years)')
plt.ylabel('value(lakhs)')
plt.title('Lasso Regression Fit (alpha=0.5)')
plt.show()
