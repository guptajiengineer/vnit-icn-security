import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
x = np.array([850,900,1000,1200,1500]).reshape((-1, 1));
y = np.array([50,55,65,80,95]);
model=LinearRegression();
model.fit(x,y);
house_size=np.array(1100).reshape((-1, 1));
predicted_price=model.predict(house_size);
print(predicted_price);
plt.scatter(x,y,color='blue');
