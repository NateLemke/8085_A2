#!/usr/bin/env python3
from enum import Enum
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import time
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, train_test_split, RandomizedSearchCV, GridSearchCV
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix, ConfusionMatrixDisplay
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.feature_selection import RFE
import pickle
from sklearn.preprocessing import MinMaxScaler
import argparse
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler
import seaborn as sns
import plotly.graph_objects as go
import plotly.express as px

PRINT_TRAINING_SCORE = False

class Classification_target(Enum):
    Label = 1
    Attack_cat = 2

class Classifier(Enum):
    RandomForestClassifier = 1
    LogisticRegression = 2
    KNearestNeighbors = 3

#region feature selection

feature_cols = ['srcip', 'sport', 'dstip', 'dsport', 'proto', 'state', 'dur', 
                'sbytes', 'dbytes', 'sttl', 'dttl', 'sloss', 'dloss', 'service', 
                'Sload', 'Dload', 'Spkts', 'Dpkts', 'swin', 'dwin', 'stcpb', 
                'dtcpb', 'smeansz', 'dmeansz', 'trans_depth', 'res_bdy_len', 
                'Sjit', 'Djit', 'Stime', 'Ltime', 'Sintpkt', 'Dintpkt', 
                'tcprtt', 'synack', 'ackdat', 'is_sm_ips_ports', 'ct_state_ttl',
                'ct_flw_http_mthd', 'is_ftp_login', 'ct_ftp_cmd', 'ct_srv_src', 
                'ct_srv_dst', 'ct_dst_ltm', 'ct_src_ ltm', 'ct_src_dport_ltm', 
                'ct_dst_sport_ltm', 'ct_dst_src_ltm']
rfc_correlated_features = ['sttl', 'ct_state_ttl', 'dttl', 'ackdat', 'state', 
                           'tcprtt']
rfc_important_features = ['proto', 'dsport', 'ct_srv_dst', 'dbytes', 'sbytes', 
                          'dmeansz', 'smeansz', 'sport', 'Dpkts']
rfc_categorical_features = ['srcip', 'dstip']

Feat15 =          ['sport', 'dsport', 'proto', 'sbytes', 'dbytes', 'sttl', 'dttl', 
                   'service', 'Sload', 'Dload', 'Dpkts', 'smeansz', 'dmeansz', 
                   'ct_state_ttl', 'ct_srv_dst']
label = ['None', 'Generic', 'Fuzzers', 'Exploits', 'Dos', 'Reconnaissance', 'Analysis', 'Shellcode', 'Backdoors', 'Worms']

#endregion

#region Dave

#
# Returns column names of features with a correlation > 0.3
# Creates heat map, bar chart, pairplot
#
def analyze_feature_correlation(df):
    # Analysis
    analysis_set = df.copy()
    analysis_set['attack_cat'], _ = pd.factorize(analysis_set['attack_cat'])

    # Create heatmap
    plt.rcParams.update({'font.size': 40}) 
    plt.rcParams['figure.figsize'] = (80, 40)
    sns.heatmap(analysis_set.corr(), annot = True)
    plt.savefig('heatmap.png')
    plt.show()

    # Create BarPlot
    correlation = analysis_set.corr().values[-2:-1].T
    plt.rcParams.update({'font.size': 72}) 
    correlation.plot(kind='bar')
    label = '{} correlated features found'.format(len(correlation))
    plt.title(label)
    plt.xlabel('Correlated features')
    plt.ylabel('Correlation coefficient')
    plt.gcf().subplots_adjust(bottom=0.4)
    plt.savefig('correlated_features')
    plt.show()

    # PairPlot
    plt.rcParams.update({'font.size': 12}) 
    sns.pairplot(df[rfc_correlated_features], diag_kind='kde')
    plt.savefig('pairplot')
    plt.show()

    correlation = analysis_set.corr().values[-2:-1]
    # Find the indices of the critical features
    correlation_keys = dict(enumerate(correlation[0]))
    # Remove label and attack_cat
    correlation_keys.popitem()
    correlation_keys.popitem()
    correlation_keys = list({key: value for key, value in correlation_keys.items() if value > 0.3}.keys())

    return df.iloc[:, correlation_keys].columns.tolist()

#
# Returns the 10 most important features according to the classifier
#
def most_important_features(df):
    x = df.iloc[:, :-2]
    y = df['attack_cat']

    classifier = RandomForestClassifier(n_estimators=1000, criterion='entropy', 
                                        max_depth=24, min_samples_split=10, 
                                        min_samples_leaf=2, max_features=None, 
                                        bootstrap=True, n_jobs=-1)
    
    frame = pd.DataFrame({'Feature': classifier.feature_names_in_, 'Importance': classifier.feature_importances_})
    return frame.sort_values(by='Importance', ascending=False)['Feature'].head(10).values.tolist()

#
# Helper function to evaluate model performance
#
def evaluate(model, test_features, test_labels):
    predictions = model.predict(test_features)
    errors = abs(predictions - test_labels)
    mean_error = np.mean(errors)
    mean_label = np.mean(test_labels)
    mape = 100 * (mean_error / mean_label)
    accuracy = 100 - mape
    print('\nModel Performance')
    print('Average Error: {:0.4f} degrees.'.format(np.mean(errors)))
    print('Accuracy = {:0.2f}%.'.format(accuracy))

    return accuracy
    
#
# Attempts to define the best possible hyperparameters for a RandomForestClassifier
#
def hyperparameter_tuning(df):
    # 1 - Create training data
    features = pd.concat([df[rfc_correlated_features], 
                          df[rfc_important_features],
                          df[rfc_categorical_features]], axis=1).columns

    x = df[features].head(20000)
    y = df.attack_cat.head(20000)
    train_features, test_features, train_labels, test_labels = train_test_split(x, y, test_size=.2, random_state=0)

    # 2 - Base model to get default params
    rf = RandomForestRegressor(random_state=42)
    
    print('Parameters currently in use:\n')
    print(rf.get_params())

    # 3 - Randomized grid search

    # Grid parameters
    n_estimators = [int(x) for x in np.linspace(start=20, stop=300, num=10)]
    max_features = ['log2', 'sqrt', None]
    max_depth = [int(x) for x in np.linspace(10, 110, num=11)]
    max_depth.append(None)
    min_samples_split = [2, 5, 10]
    min_samples_leaf = [1, 2, 4]
    bootstrap = [True, False]

    # Create the random grid
    random_grid = {'n_estimators': n_estimators,
                   'max_features': max_features,
                   'max_depth': max_depth,
                   'min_samples_split': min_samples_split,
                   'min_samples_leaf': min_samples_leaf,
                   'bootstrap': bootstrap}
    print('\nRandom Grid\n******************')
    print(random_grid)

    # Create the randomized search and establish best params
    rf = RandomForestRegressor()
    rf_random = RandomizedSearchCV(estimator=rf, 
                                   param_distributions=random_grid, n_iter=100, 
                                   cv=3, verbose=2, random_state=42, n_jobs=-1)
    
    rf_random.fit(test_features, test_labels)
    print('RF Best Params\n*****************************')
    print(rf_random.best_params_)

    base_model = RandomForestRegressor(n_estimators=10, random_state=42)
    base_model.fit(train_features, train_labels)
    base_accuracy = evaluate(base_model, test_features, test_labels)

    best_random = rf_random.best_estimator_
    random_accuracy = evaluate(best_random, test_features, test_labels)

    print('Improvement of {:0.2f}%.'.format(100 * (random_accuracy - base_accuracy) / base_accuracy))

    # 4 - Directed grid search for fine tuning

    param_grid = {
        'bootstrap': [True],
        'max_depth': [5, 20, 30, 40],
        'min_samples_leaf': [1, 2, 3],
        'min_samples_split': [2, 5, 8],
        'n_estimators': [30, 100, 200]
    }

    # Instantiate the grid search model
    grid_search = GridSearchCV(estimator=rf, param_grid=param_grid, cv=3, 
                               n_jobs=-1, verbose=2)

    # Fit the grid search to the data
    grid_search.fit(train_features, train_labels)
    print(grid_search.best_params_)

    best_grid = grid_search.best_estimator_
    grid_accuracy = evaluate(best_grid, test_features, test_labels)

    print('Improvement of {:0.2f}%.'.format(100 * (grid_accuracy - base_accuracy) / base_accuracy))

    print('\nGridSearch Best Params\n*****************************')
    print(grid_search.best_params_)

#
# Runs k fold cross validation for the given model/data
#
def k_fold_cross_validation(clf, x, y):
    print("Analyzing cross validation")
    cross_validation = cross_val_score(clf, x, y, cv=5, scoring='accuracy', n_jobs=-1)
    print(f'Cross Validation Score:\n{cross_validation}')

#endregion

#region Raymond 
def apply_knn(X_train, y_train, X_test, y_test):
    knn = KNeighborsClassifier(weights='distance',algorithm='kd_tree')
    knn.fit(X_train, y_train)
    y_predict = knn.predict(X_test)
    return y_test, y_predict

def apply_d_tree(X_train, y_train, X_test, y_test):
    clf = DecisionTreeClassifier(criterion='entropy')
    clf = clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)
    return y_test, y_pred

def apply_logistic_regression(X_train, y_train, X_test, y_test):
    log_reg = LogisticRegression(max_iter=10000)
    log_reg.fit(X_train, y_train)
    y_pred = log_reg.predict(X_test)
    return y_test, y_pred
    
def draw_heatmap(pca):
    df_comp = pd.DataFrame(pca.components_, columns=feature_cols)
    plt.figure(figsize=(12, 6))
    sns.heatmap(df_comp, cmap="Blues")
    plt.show()

def draw_diagram(pca):
    explained_variance = pca.explained_variance_ratio_
    cumulative_variance = np.cumsum(np.round(explained_variance, decimals=3))
    pc_df = pd.DataFrame(['PC1', 'PC2', 'PC3', 'PC4', 'PC5', 'PC6', 'PC7', 'PC8', 'PC9', 'PC10'], columns=['PC'])
    explained_variance_df = pd.DataFrame(explained_variance, columns=['Explained Variance'])
    cumulative_variance_df = pd.DataFrame(cumulative_variance, columns=['Cumulative Variance'])
    cumulative_variance = np.cumsum(np.round(pca.explained_variance_, decimals=3))
    df_explained_variance = pd.concat([pc_df, explained_variance_df, cumulative_variance_df], axis=1)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_explained_variance['PC'],
            y=df_explained_variance['Cumulative Variance'],
            marker=dict(size=15, color="LightSeaGreen"),
        ))
    fig.add_trace(
        go.Bar(
            x=df_explained_variance['PC'],
            y=df_explained_variance['Explained Variance'],
            marker=dict(color="RoyalBlue")
        ))


    fig.show()
#endregion
    
#region Nate
datafile = 'UNSW-NB15-BALANCED-TRAIN.csv'

Feat20 = ['sport', 'dsport', 'proto', 'state', 'sbytes', 'dbytes', 'sttl', 'dttl', 'service', 'Sload',
'Dload', 'Dpkts', 'smeansz', 'dmeansz', 'tcprtt', 'ackdat', 'ct_state_ttl', 'ct_srv_src', 'ct_srv_dst', 'ct_src_dport_ltm']
Feat15 = ['sport', 'dsport', 'proto', 'sbytes', 'dbytes', 'sttl', 'dttl', 'service', 'Sload', 'Dload', 'Dpkts', 'smeansz', 'dmeansz', 'ct_state_ttl', 'ct_srv_dst']
Feat10 = ['sport', 'dsport', 'sbytes', 'sttl', 'dttl', 'service', 'Dload', 'smeansz', 'dmeansz', 'ct_state_ttl']
Feat5 = ['sport', 'dsport', 'sbytes', 'sttl', 'ct_state_ttl']

tl= ['Benign', 'Generic', 'Fuzzers', 'Exploits', 'DOS', 'Recon', 'Backdoors', 'Analysis', 'Shellcode', 'Worms', ]

def LR_preprocessing(datafile):

    print("Reading data...")
    dataset = pd.read_csv(datafile, low_memory=False)
    
    dataset['attack_cat'] = dataset['attack_cat'].replace('Backdoor', 'Backdoors')
    dataset['attack_cat'] = dataset['attack_cat'].replace(' Fuzzers', 'Fuzzers')
    dataset['attack_cat'] = dataset['attack_cat'].replace(' Fuzzers ', 'Fuzzers')
    dataset['attack_cat'] = dataset['attack_cat'].replace(' Reconnaissance ', 'Reconnaissance')
    dataset['attack_cat'] = dataset['attack_cat'].replace(' Shellcode ', 'Shellcode')

    dataset['attack_cat'] = dataset['attack_cat'].fillna('Benign')
    dataset[['ct_flw_http_mthd','is_ftp_login']] = dataset[['ct_flw_http_mthd','is_ftp_login']].fillna(0)

    o = (dataset.dtypes == 'object')
    object_cols = list(o[o].index)

    for label in object_cols:
        dataset[label], _ = pd.factorize(dataset[label])

    cols = list(dataset.columns)
    cols.pop()
    cols.pop()

    mm = MinMaxScaler()
    dataset[cols] = mm.fit_transform(dataset[cols])

    return dataset


def LR_sampling(X,y,samples = -1):
    if samples > 0:
        sampDict = {0:samples, 1:samples}
        us = RandomUnderSampler(sampling_strategy=sampDict)
        X_train, y_train = us.fit_resample(X, y)

    print("SMOTEin'...")
    sm = SMOTE(random_state = 1, k_neighbors = 5)
    X_train, y_train = sm.fit_resample(X, y)

    return X_train, y_train


def LR_predict(X_train, y_train, X_test, y_test, show_con):

    tl= ['Benign', 'Generic', 'Fuzzers', 'Exploits', 'DOS', 'Recon', 'Backdoors', 'Analysis', 'Shellcode', 'Worms', ]

    t = time.time()

    clf = LogisticRegression(solver='saga', penalty='l1', n_jobs=-1, max_iter=100)

    print("training...")
    clf.fit(X_train, y_train)

    print("predicting...")
    y_pred = clf.predict(X_test)

    print("////////////////////////////////////////////////////////////////////////////////")
    et = time.time() - t
    print("elapsed time: ", et)

    print("Accuracy is : {:.2f}%\n".format(accuracy_score(y_test, y_pred) * 100))
    print("Classifier: Logistic Regression")
    print(classification_report(y_test, y_pred, target_names = tl))

    if show_con:
        plt.rcParams.update({'font.size': 8})
        cm = confusion_matrix(y_test, y_pred, normalize='true')
        disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=tl)
        disp.plot()
        plt.show()


def LR_FeatureSelection(datafile, num_features):

    dataset = LR_preprocessing(datafile)

    X = dataset.iloc[:, :-2].values
    y = dataset.iloc[:, -2].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=1/5, random_state=0)

    X_train, y_train = LR_sampling(X_train, y_train)

    clf = RandomForestClassifier(max_depth=10)
    sel = RFE(clf, n_features_to_select=num_features , step=10)

    t = time.process_time()
    sel = sel.fit(X_train, y_train)

    res = sel.get_support()
    indices = np.where(res)

    et = time.process_time() - t
    print("elapsed time: ", et)

    print("Selected features:")

    for i in indices[0]:
        print(dataset.columns[i])
    
    exit()


def LR_classifyLab(datafile, show_con = False):

    dataset = LR_preprocessing(datafile)

    X = dataset[Feat15].values
    y = dataset.iloc[:, -1].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=1/5, random_state=0)
    
    X_train, y_train = LR_sampling(X_train, y_train)

    LR_predict(X_train, y_train, X_test, y_test, show_con)


def LR_classifyAtk(datafile, show_con = False, sample_bool = True, samples = -1):

    dataset = LR_preprocessing(datafile)

    X = dataset[Feat15].values
    y = dataset.iloc[:, -2].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=1/5, random_state=0)

    if sample_bool:
        X_train, y_train = LR_sampling(X_train, y_train, samples)

    LR_predict(X_train, y_train, X_test, y_test, show_con)


def LR_gridSearch(datafile):

    dataset = LR_preprocessing(datafile)

    X = dataset[Feat15].values
    y = dataset.iloc[:, -2].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=1/5, random_state=0)
    
    X_train, y_train = LR_sampling(X_train, y_train)

    clf = LogisticRegression()

    print("starting grid...")
    params = [{'solver': ['lbfgs', 'liblinear', 'newton-cg', 'newton-cholesky' 'sag', 'saga' ],
               'C': [0.1, 1.0, 3.0],
               'max_iter': [100, 1000, 10000]}]
    
    grid = GridSearchCV(estimator=clf, param_grid=params, scoring='f1_macro', n_jobs=-1, verbose=3)

    grid.fit(X_train, y_train)

    print(grid.best_params_)

    pred = grid.predict(X_test)
    print(classification_report(y_test, pred, target_names=tl))

    params = [{'solver': ['saga' ],
               'penalty': ['l1', 'l2']}]
    
    grid = GridSearchCV(estimator=clf, param_grid=params, scoring='f1_macro', n_jobs=-1, verbose=3)

    grid.fit(X_train, y_train)

    print(grid.best_params_)

    pred = grid.predict(X_test)
    print(classification_report(y_test, pred, target_names=tl))
  

def LR_Sampling_Test(datafile):
    LR_classifyAtk(datafile, sample_bool= False)
    LR_classifyAtk(datafile)
    LR_classifyAtk(datafile, 100000)
    LR_classifyAtk(datafile, 50000)   
#endregion

#
# Creates and returns a dataframe for the given filename
#
def create_model(filename="UNSW-NB15-BALANCED-TRAIN.csv"):
    print(f'Loading data from {filename}')
    df = pd.read_csv(filename, header=0, low_memory=False, skipinitialspace=True)
    print("Dataset loaded\n")

    # Transform object columns
    # sport / dsport are really categorical, not numeric
    # Booleans are treated as categorical
    df['srcip'], _ = pd.factorize(df['srcip'])
    df['sport'], _ = pd.factorize(df['sport'])
    df['dstip'], _ = pd.factorize(df['dstip'])
    df['dsport'], _ = pd.factorize(df['dsport'])
    df['proto'], _ = pd.factorize(df['proto'])
    df['state'], _ = pd.factorize(df['state'])
    df['service'], _ = pd.factorize(df['service'])
    df['ct_flw_http_mthd'], _ = pd.factorize(df['ct_flw_http_mthd'])
    df['is_ftp_login'] = df['is_ftp_login'].astype(bool)
    df['is_sm_ips_ports'] = df['is_sm_ips_ports'].astype(bool)
    df['ct_ftp_cmd'], _ = pd.factorize(df['ct_ftp_cmd'])
    df['attack_cat'] = df['attack_cat'].astype('str')
    df['attack_cat'] = df['attack_cat'].str.strip()
    df['attack_cat'] = df['attack_cat'].replace('Backdoor', 'Backdoors')
    df['attack_cat'] = df['attack_cat'].replace('nan', 'Benign')
    df['Label'] = df['Label'].astype(bool)
    codes, _ = pd.factorize(df['attack_cat'])
    df['attack_cat'] = codes

    return df

#
# Applies principal component analysis
#
def apply_PCA(train,test):
    pca = PCA(n_components=10, svd_solver='full')
    pca.fit(train)
    train = pca.transform(train) 
    test = pca.transform(test)
    return train, test

#
# Creates training and test data for a given model/target
#
def df_preprocessing(df, classifier, target, apply_dimension_reduction, for_validation=False):
    scaler = None
    if classifier == Classifier.LogisticRegression:
        scaler = MinMaxScaler()
        x = scaler.fit_transform(df[Feat15])
    elif classifier == Classifier.KNearestNeighbors:
        x = df[feature_cols]
        scaler = StandardScaler()
        x = scaler.fit_transform(x)
    elif classifier == Classifier.RandomForestClassifier:
        x = df[rfc_correlated_features]
        x = pd.concat([x, df[rfc_important_features]], axis=1)
        x = pd.concat([x, df[rfc_categorical_features]], axis=1)
    else:
        if apply_dimension_reduction:
            x = df[Feat15]
        else: 
            x = df[feature_cols]
    
    if target == Classification_target.Label: 
        y = df.Label # Target variable
    elif target == Classification_target.Attack_cat:
        y = df.attack_cat
    if for_validation:
        return x, y
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=1/5, random_state=21)
    if classifier == Classifier.KNearestNeighbors and apply_dimension_reduction:
        x_train, x_test = apply_PCA(x_train, x_test)
    
    return x_train, x_test, y_train, y_test

#
#
#
def df_postprocessing(x_train, y_train):
    sm = SMOTE(random_state = 1, k_neighbors = 5)
    x_train, y_train = sm.fit_resample(x_train, y_train)
    return np.unique(y_train, return_counts=True)

#
# Returns prediction results for a model in training
#
def classify(x_train, x_test, y_train, classifier, model_loaded):
    if not model_loaded:
        classifier.fit(x_train, y_train)
    y_predict = classifier.predict(x_test)
    filename = 'Model_KNeighborsClassifier_label.pkl'
    pickle.dump(classifier, open(filename, 'wb'))
    return y_predict

#
# Returns prediction results for a trained model
#
def validation(filename, classifier_enum, classifier, target, apply_dimension_reduction):
    df = create_model(filename)
    x, y = df_preprocessing(df, classifier_enum, target, apply_dimension_reduction, for_validation=True)
    df_postprocessing(x,y)
    if classifier_enum == Classifier.KNearestNeighbors:
        pca = PCA(n_components=10, svd_solver='full')
        pca.fit(x)
        x = pca.transform(x) 

    return classifier.predict(x), y

#
# Prints prediction results to the console
#
def print_result(y_test, y_predict, classification_target):
    if PRINT_TRAINING_SCORE:
        if classification_target == Classification_target.Label:
            print(classification_report(y_test, y_predict))
        else:
            print(classification_report(y_test, y_predict, target_names=label))

def main():
    feature_reduction = True 
    data_balance = True
    model_loaded = False
    optional_load_model_name = "" 
    parser = argparse.ArgumentParser()
    parser.add_argument('heldout_filename')  
    parser.add_argument('classification_method')   
    parser.add_argument('task')   
    parser.add_argument('-m', '--model')
    parser.add_argument('-t', '--training')
    args, unknown = parser.parse_known_args()
    heldout_filename = args.heldout_filename
    filename = ""
    classification_method = args.classification_method
    task = args.task

    classifier = None
    classifier_enum = None
    
    # Set classifier
    if classification_method == "RandomForestClassifier":
        classifier = RandomForestClassifier(n_estimators=10, 
                                            criterion='entropy', max_depth=30, 
                                            min_samples_split=2,
                                            min_samples_leaf=2, 
                                            max_features=None, bootstrap=True, 
                                            n_jobs=-1)
        classifier_enum = Classifier.RandomForestClassifier 
    elif classification_method == "LogisticRegression":
        classifier = LogisticRegression(solver='saga', penalty='l1', C=3.0, max_iter=1000)
        classifier_enum = Classifier.LogisticRegression 
        model_loaded = True 
    elif classification_method == "KNearestNeighbors":
        classifier =  KNeighborsClassifier(weights='distance',algorithm='kd_tree')
        classifier_enum = Classifier.KNearestNeighbors 

    # Set target
    classification_target = None 
    if task.lower() == 'label':
        classification_target = Classification_target.Label
    else:
        classification_target = Classification_target.Attack_cat
    
    # Load model in case of Logistic Regression
    if args.model:
         optional_load_model_name = args.model
         classifier = pickle.load(open(optional_load_model_name, 'rb'))
         model_loaded = True
    elif args.training:
        filename = args.training 
    else:
        print("Invalid Input! Proper use is NIDS.py <Held-out test file> <classification method> <task>")
        print("4th arg must be either a model to load with -m or data to train from with -t")
        exit()
    start_time = time.time()
    if not model_loaded:
        # Execute
        print(f'Starting training of model')
        df = create_model(filename)
        x_train, x_test, y_train, y_test = df_preprocessing(df, classifier_enum, classification_target, feature_reduction)
        if data_balance:
            df_postprocessing(x_train, y_train)
        
        #training
        # print(x_test.shape)
        y_predict = classify(x_train, x_test, y_train, classifier, model_loaded)
        # print(classifier.classes_)
        print_result(y_test, y_predict, classification_target)
        execution_time = time.time() - start_time
        print(f'Training completed in {execution_time} seconds')
    
    #validate
    start_time = time.time()
    y_predict, y_test = validation(heldout_filename,classifier_enum, classifier, classification_target, feature_reduction)
    print_result(y_test, y_predict, classification_target)
    validation_time = time.time() - start_time
    print(f'Validation completed in {validation_time} seconds')

        
if __name__ == "__main__":
    main()
