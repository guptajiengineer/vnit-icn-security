import os
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier  # Random Forest Classifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder  # For encoding policy labels
import pickle

# Load the dataset for a specific policy
def load_dataset(policy):
    file_path = f"Simulation_Datasets/{policy}/dataset.csv"
    if os.path.exists(file_path):
        return pd.read_csv(file_path)
    else:
        print(f"Dataset for {policy} not found.")
        return None

# Preprocess the data: handle missing values, normalize, etc.
def preprocess_data(df):
    # Drop the 'Iteration' column as it is not needed for training
    df = df.drop(columns=['Iteration'])
    
    # Handle missing values (if any)
    df = df.fillna(df.mean())  # Replace NaNs with mean of each column

    # Features (X) and Target (y)
    X = df[['No of Clients', 'Total Requests', 'Hop Reduction', 'Cache Hit Ratio', 'Latency']]  # Features
    y = df['Feedback Score']  # The target is feedback score for now (replace with policy later)

    # Encode the categorical target variable (if it exists) for Random Forest Classification
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(y)

    # Split data into training and testing sets (80% train, 20% test)
    X_train, X_test, y_train, y_test = train_test_split(X, y_encoded, test_size=0.2, random_state=42)
    
    return X_train, X_test, y_train, y_test, label_encoder

# Train a Random Forest Classifier
def train_model(X_train, y_train):
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    return model

# Evaluate the model
def evaluate_model(model, X_test, y_test, label_encoder):
    y_pred = model.predict(X_test)
    
    # Convert predictions back to original labels
    y_pred_labels = label_encoder.inverse_transform(y_pred)
    y_test_labels = label_encoder.inverse_transform(y_test)

    accuracy = accuracy_score(y_test_labels, y_pred_labels)
    print(f"Accuracy: {accuracy * 100:.2f}%")
    print("Confusion Matrix:")
    print(confusion_matrix(y_test_labels, y_pred_labels))
    print("Classification Report:")
    print(classification_report(y_test_labels, y_pred_labels))

# Save the trained model to a file using pickle
def save_model(model, label_encoder, filename):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, 'wb') as file:
        pickle.dump((model, label_encoder), file)  # Save both the model and label encoder
    print(f"Model saved as {filename}")

# Main function to load data, preprocess, train and save the model for all policies
def main():
    policies = ['LRU', 'LFU', 'FIFO', 'MRU', 'FACR']  # List of policies to train models on
    all_data = []

    # Load and preprocess data for each policy
    for policy in policies:
        print(f"Loading and preprocessing data for {policy} policy...")
        
        df = load_dataset(policy)
        if df is not None:
            # Preprocess the data
            X_train, X_test, y_train, y_test, label_encoder = preprocess_data(df)

            # Add the preprocessed data to the list for combining later
            all_data.append((X_train, X_test, y_train, y_test, label_encoder))

    # Combine all the datasets
    combined_X_train = pd.concat([data[0] for data in all_data], axis=0)
    combined_X_test = pd.concat([data[1] for data in all_data], axis=0)
    
    # Convert numpy ndarray to pandas Series for proper concatenation
    combined_y_train = pd.concat([pd.Series(data[2]) for data in all_data], axis=0)
    combined_y_test = pd.concat([pd.Series(data[3]) for data in all_data], axis=0)

    # Train the Random Forest model on the combined dataset
    model = train_model(combined_X_train, combined_y_train)

    # Evaluate the model
    evaluate_model(model, combined_X_test, combined_y_test, label_encoder)

    # Save the trained model
    save_model(model, label_encoder, f'models/random_forest_model.pkl')

if __name__ == "__main__":
    main()
