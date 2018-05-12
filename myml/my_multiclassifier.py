from myml.mlassoreg import MyLASSORegression
from myml.mlogreg import MyLogisticRegression
from myml.mridgereg import MyRidgeRegression
from myml.ml2hinge import MyL2Hinge
import multiprocessing
from scipy.stats import mode
import numpy as np
import os
import pandas as pd
import time


class MultiClassifier:
    def __init__(self, x_train, y_train, parameters, x_val=None, y_val=None,
                 classification_method='ovr', n_jobs=-1, log_path='', logging_level='none'):

        cpu_count = multiprocessing.cpu_count()
        if n_jobs == -1 or n_jobs >= cpu_count:
            self.__available_procs = cpu_count
        else:
            self.__available_procs = n_jobs

        self.__classification_method = classification_method
        self.__log_path = log_path
        self.__logging_level = logging_level
        self.__parameters = parameters
        self.__x = x_train
        self.__x_val = x_val
        self.__y = y_train
        self.__y_val = y_val

        self.__manager = multiprocessing.Manager()
        self.__log_queue = self.__manager.Queue()
        self.__completion_queue = self.__manager.Queue()
        self.__snd, self.__rcv = multiprocessing.Pipe()

        self.task = classification_method
        self.cvs = self.__build_classifiers()

    def fit(self):
        log_manager = multiprocessing.Process(target=self.__log_manager,
                                              args=(self.__log_queue,
                                                    self.__snd))
        log_manager.start()

        workers = []
        for cv in self.cvs:
            # wait for other m
            if self.__available_procs == 0:
                self.__rcv.recv()
                self.__available_procs += 1

            worker = multiprocessing.Process(target=self.__train_one,
                                             args=(cv, self.__snd, self.__completion_queue))
            workers.append(worker)
            worker.start()
            time.sleep(3)

            self.__available_procs -= 1

        print('all classifiers queued for processing..\n')

        # wait for each process to finish training
        for worker in workers:
            worker.join()

        # clear the previous cv's and pull in the trained from other processes
        self.cvs.clear()
        while not self.__completion_queue.empty():
            cv_d = self.__completion_queue.get()

            if 'hinge' in cv_d['task']:
                cv_d = MyL2Hinge(x_train=None, y_train=None, parameters=None,
                                 dict_rep=cv_d)

            elif 'lasso' in cv_d['task']:
                cv_d = MyLASSORegression(x_train=None, y_train=None, parameters=None,
                                         dict_rep=cv_d)

            elif 'logistic' in cv_d['task']:
                cv_d = MyLogisticRegression(x_train=None, y_train=None, parameters=None,
                                            dict_rep=cv_d)

            elif 'ridge' in cv_d['task']:
                cv_d = MyRidgeRegression(x_train=None, y_train=None, parameters=None,
                                         dict_rep=cv_d)

            else:
                cv_d = None

            if cv_d is not None:
                self.cvs.append(cv_d)

        log_manager.terminate()
        return self

    def output_predictions(self, x):
        predictions = self.predict(x)
        pd.DataFrame(predictions).to_csv('kaggle_predictions.csv')

    def predict(self, x):
        if self.__classification_method == 'ovr':
            predictions = []
            for cv in self.cvs:
                predictions.append(cv.predict_proba(x))

            predictions = np.array(predictions).T
            predictions = [np.argmax(p) for p in predictions]
            return predictions

        elif self.__classification_method in ['all_pairs', 'both']:
            predictions = []
            for cv in self.cvs:
                if 'rest' in cv.task:
                    continue

                pre = cv.predict_with_best_fold(x)
                e = cv.task.split(' ')
                pos, neg = e[0], e[2]
                predictions.append([int(pos) if pi == 1 else int(neg) for pi in pre])
            predictions = [mode(pi).mode for pi in np.array(predictions).T]

            # break ties at random unless ovr classifiers have been fitted
            ties = [(i, pi) for i, pi in enumerate(predictions) if len(pi) > 1]
            if len(ties) > 0:
                for idx, pi in ties:
                    predictions[idx] = np.random.choice(pi)

            predictions = [int(i) for i in predictions]
            return predictions

        else:
            raise Exception('classification method not found')

    def __build_classifiers(self, method=None):
        cvs, x_idx, x_idx_v, y_v, x_v = [], [], [], [], []

        class_sets = self.__get_training_sets(method)
        for pos, neg in class_sets:
            y = np.copy(self.__y)
            x = np.copy(self.__x)
            y_v = np.copy(self.__y_val)
            x_v = np.copy(self.__x_val)

            # set class labels
            if neg == 'rest':
                pos_idx = np.where(y == int(pos))[0]
                y = y**0*-1
                y[pos_idx] = 1

                if len(x_v) > 0 and len(y_v) > 0:
                    v_pos_idx = np.where(y_v == int(pos))[0]
                    y_v = y_v**0*-1
                    y_v[v_pos_idx] = 1

            else:
                pos_idx = np.where(y == int(pos))[0]
                neg_idx = np.where(y == int(neg))[0]
                y = y**0*-1
                y[pos_idx] = 1

                x_idx = np.concatenate((pos_idx, neg_idx))
                y = y[x_idx]
                x = x[x_idx]

                if len(x_v) > 0 and len(y_v) > 0:
                    v_pos_idx = np.where(y_v == int(pos))[0]
                    v_neg_idx = np.where(y_v == int(neg))[0]

                    y_v = y_v**0*-1
                    y_v[v_pos_idx] = 1

                    x_idx_v = np.concatenate((v_pos_idx, v_neg_idx))
                    y_v = y_v[x_idx_v]
                    x_v = x_v[x_idx_v]

            task = '%s vs %s' % (pos, neg)

            for cv in self.__parameters['classifiers']:
                cv_type = cv['type']

                if cv_type == 'logistic':
                    classifier = MyLogisticRegression(x_train=x, y_train=y, x_val=x_v, y_val=y_v,
                                                      parameters=cv['parameters'],
                                                      task=task + " [logistic_regression]",
                                                      logging_level=self.__logging_level,
                                                      log_queue=self.__log_queue)

                elif cv_type == 'lasso':
                    classifier = MyLASSORegression(x_train=x, y_train=y, x_val=x_v, y_val=y_v,
                                                   parameters=cv['parameters'],
                                                   task=task + " [LASSO_regression]",
                                                   logging_level=self.__logging_level,
                                                   log_queue=self.__log_queue)

                elif cv_type == 'ridge':
                    classifier = MyRidgeRegression(x_train=x, y_train=y, x_val=x_v, y_val=y_v,
                                                   parameters=cv['parameters'],
                                                   task=task + " [ridge_regression]",
                                                   logging_level=self.__logging_level,
                                                   log_queue=self.__log_queue)

                elif cv_type == 'hinge':
                    classifier = MyL2Hinge(x_train=x, y_train=y, x_val=x_v, y_val=y_v,
                                           parameters=cv['parameters'],
                                           task=task + " [l2_hinge]",
                                           logging_level=self.__logging_level,
                                           log_queue=self.__log_queue)

                else:
                    raise Exception('classifier model not found')

                cvs.append(classifier)
        return cvs

    def __get_training_sets(self, method=None):
        classes = [str(c) for c in np.unique(self.__y)]
        pairs = []

        if method is not None:
            m = method
        else:
            m = self.__classification_method

        if m in ['ovr', 'both']:
            [pairs.append((c, 'rest')) for c in classes]

        if m in ['all_pairs', 'both']:
            for i in range(len(classes)):
                for j in range(i+1, len(classes)):
                    pairs.append((classes[i], classes[j]))

        return pairs

    def __log_manager(self, log_queue, conn):
        start = time.time()

        path = '%s/training_log_%s_%s.csv' % (self.__log_path, self.task, str(int(time.time())))

        running = len(self.cvs)
        while True:
            message = log_queue.get()

            if message == 'END_FLAG':
                running -= 1

            else:
                try:
                    with open(path, 'a+') as f:
                        f.writelines(message + "\n")
                except Exception as e:
                    print(e.args)

            if running == 0:
                break

        time_delta = time.time()-start
        print('training completed in %s\n' % time_delta)
        conn.send(True)

    def __train_one(self, cv, conn, queue):
        start = time.time()

        print("starting %s on pid %s" % (cv.task, os.getpid()))
        cv.set_log_queue(self.__log_queue)
        cv = cv.fit()

        print('%s finished %s in %s seconds' %
              (os.getpid(), cv.task, time.time() - start))

        self.__log_queue.put('END_FLAG')

        conn.send(True)
        queue.put(cv.dict)