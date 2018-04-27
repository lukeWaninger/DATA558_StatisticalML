from kaggle.my_classifier import MyClassifier
import numpy as np

# misc setup for readability
norm = np.linalg.norm
exp = np.exp
log = np.log
np.random.seed(1)


class MyLASSORegression(MyClassifier):
    def __init__(self, x_train, y_train, x_val=None, y_val=None,
                 lamda=.01, max_iter=1000, cv_splits=1, expected_betas=None,
                 log_queue=None, task=None, log_path=None):

        super().__init__(x_train, y_train, x_val, y_val,
                         lamda=lamda, cv_splits=cv_splits,
                         log_queue=log_queue, task=task, log_path=log_path)

        self.max_iter = max_iter

        self.__betas = self.coef_
        self.__exp_betas = expected_betas
        self.__objective_vals = None

    # public methods
    def fit(self, algo='random'):
        while super().fit():
            self.__betas = self.coef_

            if len(self.__betas) == 0:
                self.__betas = np.zeros(self._d)
                self._set_betas(self.__betas)

            self.__objective_vals = None

            if algo == 'random':
                self.__random_coordinate_descent()

            elif algo == 'cyclic':
                self.__cyclic_coordinate_descent()

            else:
                raise Exception("algorithm <%s> is not available" % algo)

            self._set_betas(self.__betas)
        return self

    def predict(self, x, betas=None):
        if betas is not None:
            b = betas
        elif len(self.__betas) > 0:
            b = self.__betas
        else:
            b = self.coef_

        return [1 if xi.T @ b > 0 else -1 for xi in x]

    def predict_proba(self, x, betas=None):
        if betas is not None:
            b = betas
        else:
            b = self.coef_

        return None

    def __beta_str(self):
        return ','.join([str(b) for b in self.__betas])

    def __correct_beta_percentage(self):
        return np.sum([1 for b, be in zip(self.__betas, self.__exp_betas) if np.isclose(b, be)])/self._d

    def __cyclic_coordinate_descent(self, idx=0, max_iter=None):
        if not max_iter:
            max_iter = self.max_iter

        t = 0
        while t < max_iter:
            for i in range(self._d):
                j = idx % self._d
                b0 = self.__compute_beta(j)
                self.__betas[j] = b0

                idx += 1
                self.log_metrics([
                    t, j, self.__objective(),
                    self.__correct_beta_percentage(),
                    self.__beta_str()
                ], include='reduced')
            t += 1

    def __compute_beta(self, j):
        n, l = self._n, self._lamda
        b = np.concatenate((self.__betas[:j], self.__betas[j+1:]))
        x = np.concatenate((self._x[:, :j], self._x[:, j+1:]), axis=1)

        r = self._y - x @ b
        z = np.sum(self._x[:, j]**2)

        switch = 2/self._n * norm(r)

        if abs(switch) >= l:
            bj = (-1*np.sign(switch)*l + (2/n)*self._x[:, j].T@r)/((2/n)*z)
        else:
            bj = 0
        return bj

    @staticmethod
    def __min_n1d1(x, y, l, b):
        return norm((y-x*b)) + l*abs(b)

    def __objective(self):
        x, y, n, l, b = self._x, self._y, self._n, self._lamda, self.__betas

        return (1/n)*norm(y-x @ b)**2 + l*sum(abs(b))

    def __pick_coordinate(self):
        return np.random.randint(0, self._d, 1)[0]

    def __random_coordinate_descent(self, idx=0, max_iter=None):
        if not max_iter:
            max_iter = self.max_iter

        t = 0
        while t < max_iter:
            for i in range(self._d):
                j = self.__pick_coordinate()
                b0 = self.__compute_beta(j)
                self.__betas[j] = b0

                idx += 1
                self.log_metrics([
                    t, j, self.__objective(),
                    self.__correct_beta_percentage(),
                    self.__beta_str()
                ], include='reduced')
            t += 1