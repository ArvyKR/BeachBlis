import numpy as np
import random
import json
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt
import seaborn as sns

from nltk_utils import bag_of_words, tokenize, stem
from model import NeuralNet

with open("intents.json", "r") as f:
    intents = json.load(f)

# Preprocessing data
all_words = []
tags = []
xy = []
# Loop through each sentence in our intents patterns
for intent in intents["intents"]:
    tag = intent["tag"]
    # Add to tag list
    if tag not in tags:
        tags.append(tag)
    for pattern in intent["patterns"]:
        # Tokenize each word in the sentence
        w = tokenize(pattern)
        # Add to our words list
        all_words.extend(w)
        # Add to xy pair
        xy.append((w, tag))

# Stem and lower each word
ignore_words = ["?", ".", "!"]
all_words = [stem(w) for w in all_words if w not in ignore_words]

# Remove duplicates and sort
all_words = sorted(set(all_words))
tags = sorted(set(tags))

print(len(xy), "patterns")
print(len(tags), "tags:", tags)
print(len(all_words), "unique stemmed words:", all_words)
# End preprocessing data

# Create training data
X = []
y = []
for pattern_sentence, tag in xy:
    # X: bag of words for each pattern_sentence
    bag = bag_of_words(pattern_sentence, all_words)
    X.append(bag)
    # y: PyTorch CrossEntropyLoss needs only class labels
    label = tags.index(tag)
    y.append(label)

X = np.array(X)
y = np.array(y)

# Split the dataset into training and test sets
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Hyper-parameters
num_epochs = 600
batch_size = 10
learning_rate = 0.002
input_size = len(X_train[0])
hidden_size1 = 128
hidden_size2 = 64
output_size = len(tags)
patience = 25

print(input_size, output_size)


class ChatDataset(Dataset):
    def __init__(self, X, y):
        self.n_samples = len(X)
        self.x_data = X
        self.y_data = y

    def __getitem__(self, index):
        return self.x_data[index], self.y_data[index]

    def __len__(self):
        return self.n_samples


train_dataset = ChatDataset(X_train, y_train)
train_loader = DataLoader(
    dataset=train_dataset, batch_size=batch_size, shuffle=True, num_workers=0
)

test_dataset = ChatDataset(X_test, y_test)
test_loader = DataLoader(
    dataset=test_dataset, batch_size=batch_size, shuffle=False, num_workers=0
)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

model = NeuralNet(input_size, hidden_size1, hidden_size2, output_size).to(device)

# Loss and optimizer
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=1e-5)
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=50, gamma=0.1)

# Training model with early stopping
best_macro_f1 = 0
trigger_times = 0


def compute_confusion_matrix_and_metrics(labels, predictions, num_classes):
    conf_matrix = np.zeros((num_classes, num_classes), dtype=int)
    for t, p in zip(labels, predictions):
        conf_matrix[t, p] += 1

    with np.errstate(divide="ignore", invalid="ignore"):
        precision = np.diag(conf_matrix) / np.sum(conf_matrix, axis=0)
        recall = np.diag(conf_matrix) / np.sum(conf_matrix, axis=1)
        f1_score = 2 * precision * recall / (precision + recall)

    precision = np.nan_to_num(precision)
    recall = np.nan_to_num(recall)
    f1_score = np.nan_to_num(f1_score)

    return conf_matrix, precision, recall, f1_score


for epoch in range(num_epochs):
    model.train()
    for words, labels in train_loader:
        words = words.to(device)
        labels = labels.to(dtype=torch.long).to(device)

        outputs = model(words)
        loss = criterion(outputs, labels)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

    scheduler.step()

    model.eval()
    all_predictions = []
    all_labels = []

    with torch.no_grad():
        for words, labels in test_loader:
            words = words.to(device)
            labels = labels.to(dtype=torch.long).to(device)
            outputs = model(words)
            _, predicted = torch.max(outputs, 1)
            all_predictions.extend(predicted.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())

    conf_matrix, precision, recall, f1_score = compute_confusion_matrix_and_metrics(
        all_labels, all_predictions, len(tags)
    )

    macro_precision = np.mean(precision)
    macro_recall = np.mean(recall)
    macro_f1_score = np.mean(f1_score)

    if macro_f1_score > best_macro_f1:
        best_macro_f1 = macro_f1_score
        trigger_times = 0
        torch.save(model.state_dict(), "best_model.pth")
    else:
        trigger_times += 1

    if trigger_times >= patience:
        print(f"Early stopping at epoch {epoch + 1}")
        break

    if (epoch + 1) % 1 == 0:
        print(
            f"Epoch [{epoch+1}/{num_epochs}], Loss: {loss.item():.4f}, Macro F1 Score: {macro_f1_score:.4f}"
        )

model.load_state_dict(torch.load("best_model.pth"))

# Evaluation on the test data
model.eval()
all_predictions = []
all_labels = []

with torch.no_grad():
    for words, labels in test_loader:
        words = words.to(device)
        labels = labels.to(dtype=torch.long).to(device)
        outputs = model(words)
        _, predicted = torch.max(outputs, 1)
        all_predictions.extend(predicted.cpu().numpy())
        all_labels.extend(labels.cpu().numpy())

conf_matrix, precision, recall, f1_score = compute_confusion_matrix_and_metrics(
    all_labels, all_predictions, len(tags)
)

print("Confusion Matrix:")
print(conf_matrix)

print(f"\nPrecision per class: {precision}")
print(f"Recall per class: {recall}")
print(f"F1 Score per class: {f1_score}")

# Overall (macro) metrics
macro_precision = np.mean(precision)
macro_recall = np.mean(recall)
macro_f1_score = np.mean(f1_score)

print(f"Macro Precision: {macro_precision:.4f}")
print(f"Macro Recall: {macro_recall:.4f}")
print(f"Macro F1 Score: {macro_f1_score:.4f}")

# Calculate accuracy
accuracy = np.sum(np.diag(conf_matrix)) / np.sum(conf_matrix)
print(f"\nAccuracy: {accuracy:.4f}")

# Plot the confusion matrix
plt.figure(figsize=(10, 8))
sns.heatmap(
    conf_matrix, annot=True, fmt="d", cmap="Blues", xticklabels=tags, yticklabels=tags
)
plt.xlabel("Predicted")
plt.ylabel("True")
plt.title("Confusion Matrix")
plt.show()

# Calculate percentages per class (row-wise)
row_sums = conf_matrix.sum(axis=1, keepdims=True)
conf_matrix_percent = np.where(row_sums > 0, (conf_matrix / row_sums) * 100, 0)

# Plot the confusion matrix with percentages
plt.figure(figsize=(12, 10))
sns.heatmap(
    conf_matrix_percent,
    annot=True,
    fmt=".1f",
    cmap="Blues",
    xticklabels=tags,
    yticklabels=tags,
)
plt.xticks(rotation=80)
plt.yticks(rotation=0)
plt.xlabel("Predicted")
plt.ylabel("True")
plt.title("Confusion Matrix (%)")
plt.tight_layout()
plt.show()
