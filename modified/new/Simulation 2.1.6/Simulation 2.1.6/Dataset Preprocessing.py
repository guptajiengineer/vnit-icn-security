import os
import pandas as pd
from sklearn.preprocessing import OneHotEncoder
from sklearn.preprocessing import StandardScaler

# Define the path where the ML training data is located
base_dir = "ML_Training_Data"

# Function to load and preprocess the datasets
def load_and_preprocess_data(base_dir):
    # List to store all dataframes
    dfs = []

    # Iterate through each folder (policy) in the base directory
    for policy in os.listdir(base_dir):
        policy_dir = os.path.join(base_dir, policy)
        if os.path.isdir(policy_dir):  # Check if it's a folder
            features_file = os.path.join(policy_dir, 'features.csv')
            
            # Load the CSV file
            if os.path.exists(features_file):
                print(f"Loading data from {features_file}")
                df = pd.read_csv(features_file)
                
                # Add a 'Policy' column to indicate the policy (folder name)
                df['Policy'] = policy  # The policy name (folder) is added to each row

                # Preprocess the 'Feedback Scores' column
                encoder = OneHotEncoder(sparse_output=False)  # Updated parameter
                feedback_matrix = encoder.fit_transform(
                    df['Feedback Scores'].apply(lambda x: x.strip("[]").replace("'", "").split(',')).tolist()
                )
                feedback_df = pd.DataFrame(feedback_matrix, columns=encoder.get_feature_names_out())

                # Concatenate the feedback columns with the original dataframe
                df = pd.concat([df, feedback_df], axis=1)
                df = df.drop(columns=['Feedback Scores'])  # Drop the original 'Feedback Scores' column

                # Normalize continuous columns
                continuous_columns = ['No of Clients', 'Total Requests', 'Hop Reduction', 'Cache Hit Ratio', 'Latency']
                scaler = StandardScaler()
                df[continuous_columns] = scaler.fit_transform(df[continuous_columns])

                # Append the preprocessed dataframe to the list
                dfs.append(df)
            else:
                print(f"File {features_file} does not exist.")

    # Concatenate all dataframes into one
    combined_df = pd.concat(dfs, ignore_index=True)
    return combined_df

# Load and preprocess data
processed_data = load_and_preprocess_data(base_dir)

# Save the processed data to a CSV file (optional)
processed_data.to_csv("Processed_Features_with_Policy.csv", index=False)
print("Processed data saved to 'Processed_Features_with_Policy.csv'.")
