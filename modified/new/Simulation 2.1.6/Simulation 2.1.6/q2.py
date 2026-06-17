import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression

x = np.array([1, 2, 3, 4, 5, 6]).reshape((-1, 1))
y = np.array([25, 30, 35, 40, 45, 52])

# Fit linear regression model
model = LinearRegression().fit(x, y)

# Predict for x=3.5
expected_salary = model.predict(np.array([3.5]).reshape((-1, 1)))
print(expected_salary)

# Scatter plot of data points
plt.scatter(x, y, color='blue')

# Plot regression line
x_line = np.linspace(x.min(), x.max(), 100).reshape(-1, 1)  # smooth range for x
y_line = model.predict(x_line)  # predicted y values from model
plt.plot(x_line, y_line, color='red')

plt.xlabel('experience')
plt.ylabel('salary')
plt.title('Linear Regression Fit')
plt.show()
