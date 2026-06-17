import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression

x = np.array([22,25,27,30,33]).reshape((-1, 1));
y = np.array([120,150,170,210,240]);
# Fit linear regression model
model = LinearRegression().fit(x, y)

expected_sales = model.predict(np.array([28]).reshape((-1, 1)))
print(expected_sales)

# Scatter plot of data points
plt.scatter(x, y, color='blue')

# Plot regression line
x_line = np.linspace(x.min(), x.max(), 100).reshape(-1, 1)  # smooth range for x
y_line = model.predict(x_line)  # predicted y values from model
plt.plot(x_line, y_line, color='red')

plt.xlabel('temperature')
plt.ylabel('sales')
plt.title('Linear Regression Fit')
plt.show()