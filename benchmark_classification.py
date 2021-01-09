import pandas as pd
import numpy as np
from ember.impute import GeneralImputer
from ember.optimize import GridSelector, BayesSelector
from ember.utils import DtypeSelector
from sklearn.model_selection import train_test_split
from ember.preprocessing import Preprocessor, GeneralEncoder, GeneralScaler
from ember.optimize import BaesianSklearnSelector
from sklearn.metrics import r2_score, accuracy_score
from ember.search_space import get_baesian_space
from xgboost import XGBClassifier
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
import tqdm
import datetime
import json
import neptune
from skopt import BayesSearchCV
from skopt.callbacks import DeltaYStopper, DeltaXStopper
import os

objective = 'classification'

token = 'eyJhcGlfYWRkcmVzcyI6Imh0dHBzOi8vdWkubmVwdHVuZS5haSIsImFwaV91cmwiOiJodHRwczovL3VpLm5lcHR1bmUuYWkiLCJhcGlfa2V5IjoiYTFlODM1OWItZWMxMC00Yzg1LWE0YmMtMzkwNmUxYWI1ZmZlIn0='
project_name = 'damiankucharski/bayes-cv-split'
neptune.init(project_qualified_name= project_name, # change this to your `workspace_name/project_name`
             api_token=token, # change this to your api token
            )


def preproces_data(X,y, target='class', objective='regression'):


    target_preprocessor = Preprocessor()
    target_preprocessor.add_branch('target')

    if y.dtype == np.object:

        target_preprocessor.add_transformer_to_branch('target', GeneralImputer('Simple', 'most_frequent'))
        target_preprocessor.add_transformer_to_branch('target', GeneralEncoder('LE'))
    else:
        if objective == 'classification':
            target_preprocessor.add_transformer_to_branch('target', GeneralImputer('Simple', 'most_frequent'))
        elif objective == 'regression':
            target_preprocessor.add_transformer_to_branch('target', GeneralImputer('Simple', 'mean'))
        else:
            pass

            ## features pipeline ##

    feature_preprocessor = Preprocessor()

    is_number = len(X.select_dtypes(include=np.number).columns.tolist()) > 0
    is_object = len(X.select_dtypes(include=np.object).columns.tolist()) > 0

    if is_object:
        feature_preprocessor.add_branch("categorical")
        feature_preprocessor.add_transformer_to_branch("categorical", DtypeSelector(np.object))
        feature_preprocessor.add_transformer_to_branch("categorical",
                                                       GeneralImputer('Simple', strategy='most_frequent'))
        feature_preprocessor.add_transformer_to_branch("categorical", GeneralEncoder(kind='OHE'))

    if is_number:
        feature_preprocessor.add_branch('numerical')
        feature_preprocessor.add_transformer_to_branch("numerical", DtypeSelector(np.number))
        feature_preprocessor.add_transformer_to_branch("numerical", GeneralImputer('Simple'))
        feature_preprocessor.add_transformer_to_branch("numerical", GeneralScaler('SS'))

    feature_preprocessor = feature_preprocessor.merge()
    target_preprocessor = target_preprocessor.merge()

    y = np.array(y).reshape(-1, 1)
    y = target_preprocessor.fit_transform(y).ravel()
    X = feature_preprocessor.fit_transform(X)
    return X, y

def change_df_column(df,to_change,new_name):
    df_columns = list(df.columns)
    for idx,column in enumerate(df_columns):
        if column == to_change:
            df_columns[idx] = new_name
    df.columns = df_columns

def get_lgbm_score(X_train,y_train,X_test,y_test):
    lgbm_default = LGBMClassifier()
    lgbm_default.fit(X_train, y_train)
    score_lgbm = accuracy_score(y_test, lgbm_default.predict(X_test))
    neptune.log_metric('lgbm', score_lgbm)
    return score_lgbm

def get_xgb_score(X_train,y_train,X_test,y_test):
    xgb_default = XGBClassifier()
    xgb_default.fit(X_train, y_train)
    score_xgb = accuracy_score(y_test, xgb_default.predict(X_test))
    neptune.log_metric('xgb', score_xgb)
    return score_xgb

def get_cat_score(X_train,y_train,X_test,y_test):
    cat_default = CatBoostClassifier(logging_level="Silent")
    cat_default.fit(X_train, y_train)
    score_cat = accuracy_score(y_test, cat_default.predict(X_test))
    neptune.log_metric('cat', score_cat)
    return score_cat
def get_grid_score(X_train,y_train,X_test,y_test,folds=5):
    model = GridSelector('classification',folds=folds, steps=6)
    model.fit(X_train, y_train)
    score = accuracy_score(y_test, model.predict(X_test))
    neptune.log_metric('grid', score)
    return score
def get_bayes_score(X_train,y_train,X_test,y_test,folds=5):
    model = BayesSelector('classification', cv=folds, max_evals=10)
    model.fit(X_train, y_train)
    score = accuracy_score(y_test, model.predict(X_test))
    neptune.log_metric('hyperopt', score)
    return score

def get_bayes_scikit_score(X_train,y_train,X_test,y_test, X_val=None, y_val= None, max_evals = 25, folds=5):

    model = BaesianSklearnSelector('classification', X_test=X_test, y_test = y_test, max_evals= max_evals)
    model.fit(X_train, y_train)
    score = accuracy_score(y_val, model.predict(X_val))
    neptune.log_metric(f'skopt-{max_evals}-iterations', score)
    return score

def get_bayes_scikit_score_cv(X_train,y_train,X_test,y_test, X_val=None, y_val= None, max_evals = 25, folds=5, original = None):

    space = get_baesian_space(dictem = True)
    opt_cat = BayesSearchCV(CatBoostClassifier(logging_level='Silent'), space['CAT'], n_iter = max_evals, random_state = 0)
    opt_xgb = BayesSearchCV(XGBClassifier(), space['XGB'], n_iter = max_evals, random_state = 0)
    opt_lgbm = BayesSearchCV(LGBMClassifier(), space['LGBM'], n_iter = max_evals, random_state = 0)
    _ = opt_cat.fit(X_train, y_train, callback = [DeltaXStopper(0.01), DeltaYStopper(0.01)])
    __ = opt_xgb.fit(X_train, y_train, callback = [DeltaXStopper(0.01), DeltaYStopper(0.01)])
    ___ = opt_lgbm.fit(X_train, y_train, callback = [DeltaXStopper(0.01), DeltaYStopper(0.01)])

    scores = [opt_cat.score(X_test, y_test), opt_xgb.score(X_test, y_test), opt_lgbm.score(X_test, y_test)]
    score = max(scores)

    neptune.log_metric(f'skopt-{max_evals}-iterations-{folds}-folds', score)
    return score

def evaluate_single():

    path = r'datasets/classification'
    names = os.listdir(path)
    names = sorted(names)
    datasets = [{"name":x,"target_column":"class"} for x in names]

    for dataset in tqdm.tqdm(datasets[1:]):
        try:
          neptune.create_experiment(name = dataset['name'])
          print('Training ' + dataset['name'])
          data = pd.read_csv(path + '/' + dataset["name"])
          change_df_column(data, dataset['target_column'], 'class')
          X, y = data.drop(columns=['class']), data['class']
          X,y = preproces_data(X,y)
          X_train, X_test, y_train, y_test = train_test_split(X, y, stratify = y, random_state=42, test_size=0.3)
          print('cat')
          get_cat_score(_X_train, _y_train, _X_test, _y_test)
          print('lgbm')
          get_lgbm_score(X_train,y_train,X_test,y_test)
          print('xgb')
          get_xgb_score(X_train, y_train, X_test, y_test)
          # print('grid')
          # get_grid_score(X_train, y_train, X_test, y_test)
          print('bayes-cv')
          get_bayes_scikit_score_cv(X_train, y_train, X_test, y_test, folds = 5, max_evals = 30)
        #   print('bayes-10')
        #   get_bayes_scikit_score(X_train, y_train, X_test, y_test, X_val, y_val, max_evals = 10)
        #   print('bayes-15')
        #   get_bayes_scikit_score(X_train, y_train, X_test, y_test, X_val, y_val, max_evals = 15)
        #   print('bayes-25')
        #   get_bayes_scikit_score(X_train, y_train, X_test, y_test, X_val, y_val, max_evals = 25)
         
        except Exception as ex:
          print(ex)
          neptune.log_metric('failed')
if __name__ == '__main__':
    
    evaluate_single()

