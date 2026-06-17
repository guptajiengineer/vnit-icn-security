import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
import pickle
import os

# Load the dataset
df = pd.read_csv("Processed_Features_with_Policy.csv")

# Drop 'Simulation Time' as it's not a feature for prediction
df = df.drop(columns=['Simulation Time'])

# Convert 'Policy' into a categorical variable (Target variable)
df['Policy'] = df['Policy'].astype('category')

# Features are all columns except 'Policy'
X = df.drop(columns=['Policy'])

# Target variable is 'Policy'
y = df['Policy']

# Split data into train and test sets (80% train, 20% test)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Initialize and train the Random Forest model
rf_model = RandomForestClassifier(n_estimators=100, random_state=42)
rf_model.fit(X_train, y_train)

# Predict the policy on the test set
y_pred = rf_model.predict(X_test)

# Print the classification report to evaluate the model's performance
print("Classification Report:\n", classification_report(y_test, y_pred))

# Create the 'model' directory if it doesn't exist
os.makedirs('model', exist_ok=True)

# Save the trained model to a file
model_filename = 'model/random_forest_model.pkl'
with open(model_filename, 'wb') as f:
    pickle.dump(rf_model, f)

print(f"Model saved successfully as '{model_filename}'")
