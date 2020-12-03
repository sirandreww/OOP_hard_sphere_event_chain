#!/Local/cmp/anaconda3/bin/python -u
import numpy as np
from SnapShot import *
from Structure import *
from EventChainActions import *
from sklearn.neighbors import *
import os
import sys
import random
import re
from datetime import date
from scipy.spatial import Delaunay
from scipy.optimize import fmin
import time

epsilon = 1e-8
day = 86400  # sec


class OrderParameter:

    def __init__(self, sim_path, centers=None, spheres_ind=None, calc_upper_lower=False, **kwargs):
        self.sim_path = sim_path
        write_or_load = WriteOrLoad(sim_path)
        l_x, l_y, l_z, rad, rho_H, edge, n_row, n_col = write_or_load.load_Input()
        self.event_2d_cells = Event2DCells(edge, n_row, n_col, l_z)
        if centers is None or spheres_ind is None:
            centers, spheres_ind = write_or_load.last_spheres()
        self.spheres_ind = spheres_ind
        self.event_2d_cells.append_sphere([Sphere(c, rad) for c in centers])
        self.spheres = self.event_2d_cells.all_centers
        self.write_or_load = WriteOrLoad(sim_path, self.event_2d_cells.boundaries)
        self.N = len(centers)

        self.op_vec = None
        self.op_corr = None
        self.corr_centers = None
        self.counts = None

        self.op_name = "phi"
        if calc_upper_lower:
            upper_centers = [c for c in self.spheres if c[2] >= self.event_2d_cells.boundaries[2] / 2]
            lower_centers = [c for c in self.spheres if c[2] < self.event_2d_cells.boundaries[2] / 2]
            self.upper = type(self)(sim_path, centers=upper_centers, spheres_ind=self.spheres_ind,
                                    calc_upper_lower=False, **kwargs)
            self.lower = type(self)(sim_path, centers=lower_centers, spheres_ind=self.spheres_ind,
                                    calc_upper_lower=False, **kwargs)

    def calc_order_parameter(self, calc_upper_lower=False):
        """to be override by child class"""
        pass

    def correlation(self, bin_width=0.2, calc_upper_lower=False, low_memory=True, randomize=False,
                    realizations=int(1e7), time_limit=2 * day):
        if self.op_vec is None: self.calc_order_parameter()
        lx, ly = self.event_2d_cells.boundaries[:2]
        l = np.sqrt(lx ** 2 + ly ** 2) / 2
        centers = np.linspace(0, np.ceil(l / bin_width) * bin_width, int(np.ceil(l / bin_width)) + 1) + bin_width / 2
        kmax = len(centers) - 1
        counts = np.zeros(len(centers))
        phiphi_hist = np.zeros(len(centers))
        init_time = time.time()
        N = len(self.spheres)
        if low_memory:
            if randomize:
                for realization in range(realizations):
                    i, j = random.randint(0, N - 1), random.randint(0, N - 1)
                    phi_phi, k = self.__pair_corr__(i, j, bin_width)
                    k = int(min(k, kmax))
                    counts[k] += 2
                    phiphi_hist[k] += 2 * np.real(phi_phi)
                    if realization % 1000 == 0 and time.time() - init_time > time_limit:
                        break
            else:
                for i in range(N):
                    for j in range(i):  # j<i, j=i not interesting and j>i double counting accounted for in counts
                        phi_phi, k = self.__pair_corr__(i, j, bin_width)
                        k = int(min(k, l))
                        counts[k] += 2  # r-r' and r'-r
                        phiphi_hist[k] += 2 * np.real(phi_phi)  # a+a'=2Re(a)
                realization = N * (N - 1) / 2
        else:
            N = len(self.op_vec)
            v = np.array(self.op_vec).reshape(1, N)
            phiphi_vec = (np.conj(v) * v.T).reshape((N ** 2,))
            x = np.array([r[0] for r in self.spheres])
            y = np.array([r[1] for r in self.spheres])
            dx = (x.reshape((len(x), 1)) - x.reshape((1, len(x)))).reshape(len(x) ** 2, )
            dy = (y.reshape((len(y), 1)) - y.reshape((1, len(y)))).reshape(len(y) ** 2, )
            dx = np.minimum(np.abs(dx), np.minimum(np.abs(dx + lx), np.abs(dx - lx)))
            dy = np.minimum(np.abs(dy), np.minimum(np.abs(dy + ly), np.abs(dy - ly)))
            pairs_dr = np.sqrt(dx ** 2 + dy ** 2)

            I = np.argsort(pairs_dr)
            pairs_dr = pairs_dr[I]
            phiphi_vec = phiphi_vec[0, I]
            i = 0
            for j in range(len(pairs_dr)):
                if pairs_dr[j] > centers[i] + bin_width / 2:
                    i += 1
                phiphi_hist[i] += np.real(phiphi_vec[0, j])
                counts[i] += 1
            realization = N ** 2
        print("\nTime Passed: " + str((time.time() - init_time) / day) + " days.\nSummed " + str(
            realization) + " pairs")
        self.counts = counts
        self.op_corr = phiphi_hist / counts
        self.corr_centers = centers

        if calc_upper_lower:
            self.lower.correlation(bin_width, low_memory=low_memory, randomize=randomize, realizations=realizations)
            self.upper.correlation(bin_width, low_memory=low_memory, randomize=randomize, realizations=realizations)

    def __pair_corr__(self, i, j, bin_width):
        lx, ly = self.event_2d_cells.boundaries[:2]
        r, r_ = self.spheres[i], self.spheres[j]
        dr_vec = np.array(r) - r_
        dx = np.min(np.abs([dr_vec[0], dr_vec[0] + lx, dr_vec[0] - lx]))
        dy = np.min(np.abs([dr_vec[1], dr_vec[1] + ly, dr_vec[1] - ly]))
        dr = np.sqrt(dx ** 2 + dy ** 2)
        k = int(np.floor(dr / bin_width))
        return self.op_vec[i] * np.conjugate(self.op_vec[j]), k

    def write(self, write_correlation=True, write_vec=False, write_upper_lower=False, vec_name="vec",
              correlation_name="correlation"):
        join = lambda a, b: os.path.join(a, b)
        op_dir = join(self.sim_path, "OP")
        op_name_dir = join(op_dir, self.op_name)
        save_mat = lambda name, mat: np.savetxt(join(op_name_dir, name + "_" + str(self.spheres_ind) + ".txt"), mat)
        if not os.path.exists(op_dir): os.mkdir(op_dir)
        if not os.path.exists(op_name_dir): os.mkdir(op_name_dir)
        if write_vec:
            if self.op_vec is None: raise (Exception("Should calculate correlation before writing"))
            save_mat(vec_name, self.op_vec)
        if write_correlation:
            if self.op_corr is None: raise (Exception("Should calculate correlation before writing"))
            save_mat(correlation_name, np.transpose([self.corr_centers, self.op_corr, self.counts]))
        if write_upper_lower:
            self.lower.write(write_correlation, write_vec, write_upper_lower=False)
            self.upper.write(write_correlation, write_vec, write_upper_lower=False)


class PsiMN(OrderParameter):

    def __init__(self, sim_path, m, n, centers=None, spheres_ind=None, calc_upper_lower=False):
        super().__init__(sim_path, centers, spheres_ind, calc_upper_lower, m=1, n=m * n)
        # extra args m,n goes to upper and lower layers
        self.m, self.n = m, n
        self.op_name = "psi_" + str(m) + str(n)
        if calc_upper_lower:
            self.upper.op_name = "upper_psi_1" + str(n * m)
            self.lower.op_name = "lower_psi_1" + str(n * m)

    @staticmethod
    def psi_m_n(event_2d_cells, m, n):
        centers = event_2d_cells.all_centers
        cyc = lambda p1, p2: Metric.cyclic_dist(event_2d_cells.boundaries, Sphere([x for x in p1] + [0], 1),
                                                Sphere([x for x in p2] + [0], 1))
        graph = kneighbors_graph([p[:2] for p in centers], n_neighbors=n, metric=cyc)
        psimn_vec = np.zeros(len(centers), dtype=np.complex)
        for i in range(len(centers)):
            dr = [np.array(centers[i]) - centers[j] for j in graph.getrow(i).indices]
            t = np.arctan2([r[1] for r in dr], [r[0] for r in dr])
            psi_n = np.mean(np.exp(1j * n * t))
            psimn_vec[i] = np.abs(psi_n) * np.exp(1j * m * np.angle(psi_n))
        return psimn_vec, graph

    def calc_order_parameter(self, calc_upper_lower=False):
        self.op_vec, _ = PsiMN.psi_m_n(self.event_2d_cells, self.m, self.n)
        if calc_upper_lower:
            self.lower.calc_order_parameter()
            self.upper.calc_order_parameter()

    def rotate_spheres(self, calc_spheres=True):
        n_orientation = self.m * self.n
        psi_avg = np.mean(self.op_vec)
        orientation = np.imag(np.log(psi_avg)) / n_orientation
        if not calc_spheres:
            return orientation
        else:
            R = np.array([[np.cos(orientation), np.sin(orientation), 0], [-np.sin(orientation), np.cos(orientation), 0],
                          [0.0, 0.0, 1.0]])  # rotate back from orientation-->0
            return orientation, [np.matmul(R, r) for r in self.spheres]


class PositionalCorrelationFunction(OrderParameter):

    def __init__(self, sim_path, psi_op, rect_width=0.2, centers=None, spheres_ind=None, calc_upper_lower=False):
        super().__init__(sim_path, centers, spheres_ind, calc_upper_lower, psi_op=psi_op, rect_width=rect_width)
        self.theta = psi_op.rotate_spheres(calc_spheres=False)
        self.rect_width = rect_width
        self.op_name = "pos"
        if calc_upper_lower:
            self.upper.op_name = "upper_" + self.op_name
            self.lower.op_name = "lower_" + self.op_name

    def correlation(self, bin_width=0.2, calc_upper_lower=False, low_memory=True, randomize=False,
                    realizations=int(1e7), time_limit=2 * day):
        theta, rect_width = self.theta, self.rect_width
        v_hat = np.array([np.cos(theta), np.sin(theta)])
        lx, ly = self.event_2d_cells.boundaries[:2]
        l = np.sqrt(lx ** 2 + ly ** 2) / 2
        bins_edges = np.linspace(0, np.ceil(l / bin_width) * bin_width, int(np.ceil(l / bin_width)) + 1)
        kmax = len(bins_edges) - 1
        self.corr_centers = bins_edges[:-1] + bin_width / 2
        self.counts = np.zeros(len(self.corr_centers))
        init_time = time.time()
        N = len(self.spheres)
        if low_memory:
            if randomize:
                for realization in range(realizations):
                    i, j = random.randint(0, N - 1), random.randint(0, N - 1)
                    k = self.__pair_dist__(self.spheres[i], self.spheres[j], v_hat, rect_width)
                    if k is not None:
                        k = int(min(k, kmax))
                        self.counts[k] += 1
                    if realization % 1000 == 0 and time.time() - init_time > time_limit:
                        break
            else:
                for i in range(N):
                    for j in range(i):
                        k = self.__pair_dist__(self.spheres[i], self.spheres[j], v_hat, rect_width)
                        if k is not None:
                            k = int(min(k, kmax))
                            self.counts[k] += 1
                realization = N * (N - 1) / 2
        else:
            x = np.array([r[0] for r in self.spheres])
            y = np.array([r[1] for r in self.spheres])
            N = len(x)
            dx = (x.reshape((N, 1)) - x.reshape((1, N))).reshape(N ** 2, )
            dy = (y.reshape((N, 1)) - y.reshape((1, N))).reshape(N ** 2, )
            A = np.transpose([dx, dx + lx, dx - lx])
            I = np.argmin(np.abs(A), axis=1)
            J = [i for i in range(len(I))]
            dx = A[J, I]
            A = np.transpose([dy, dy + ly, dy - ly])
            I = np.argmin(np.abs(A), axis=1)
            dy = A[J, I]

            pairs_dr = np.transpose([dx, dy])

            m = lambda A, B: np.matmul(A, B)
            dist_vec = m(v_hat.reshape(2, 1), m(pairs_dr, v_hat).reshape(1, N)).T - pairs_dr
            dist_to_line = np.linalg.norm(dist_vec, axis=1)
            I = np.where(dist_to_line <= rect_width / 2)[0]
            pairs_dr = pairs_dr[I]
            J = np.where(m(pairs_dr, v_hat) > 0)[0]
            pairs_dr = pairs_dr[J]
            rs = m(pairs_dr, v_hat)
            self.counts, _ = np.histogram(rs, bins_edges)
            realization = N ** 2
        print("\nTime Passed: " + str((time.time() - init_time) / day) + " days.\nSummed " + str(
            realization) + " pairs")
        self.op_corr = self.counts / np.nanmean(self.counts[np.where(self.counts > 0)])

        if calc_upper_lower:
            assert self.upper is not None, \
                "Failed calculating upper positional correlation because it was not initialized"
            self.upper.correlation(bin_width=bin_width, low_memory=low_memory, randomize=randomize,
                                   realizations=realizations)
            assert self.upper is not None, \
                "Failed calculating lower positional correlation because it was not initialized"
            self.lower.correlation(bin_width=bin_width, low_memory=low_memory, randomize=randomize,
                                   realizations=realizations)

    def __pair_dist__(self, r, r_, v_hat, rect_width):
        lx, ly = self.event_2d_cells.boundaries[:2]
        dr = np.array(r) - r_
        dxs = [dr[0], dr[0] + lx, dr[0] - lx]
        dx = dxs[np.argmin(np.abs(dxs))]
        dys = [dr[1], dr[1] + ly, dr[1] - ly]
        dy = dys[np.argmin(np.abs(dys))]
        dr = np.array([dx, dy])
        dist_on_line = float(np.dot(dr, v_hat))
        dist_vec = v_hat * dist_on_line - dr
        dist_to_line = np.linalg.norm(dist_vec)
        if dist_to_line <= rect_width / 2 and dist_on_line > 0:
            k = int(np.floor(dist_on_line / rect_width))
            return k
        else:
            return None

    def write(self, write_correlation=True, write_vec=False, write_upper_lower=False):
        super().write(write_correlation, write_vec, write_upper_lower,
                      correlation_name="correlation_theta=" + str(self.theta))


class PsiUpPsiDown(PsiMN):
    def __init__(self, sim_path, m, n, centers=None, spheres_ind=None):
        super().__init__(sim_path, m, n, centers, spheres_ind, calc_upper_lower=True)
        self.op_orig = self.op_name
        self.op_name = "psiup_psidown_" + str(m) + str(n)

    def calc_order_parameter(self):
        super().calc_order_parameter(calc_upper_lower=True)
        self.op_orig = self.op_vec


class RealizationsAveragedOP:

    def __init__(self, num_realizations, op_type, op_args):
        """

        :type sim_path: str
        :type num_realizations: int
        :param op_type: OrderParameter. Example: op_type = PsiMn
        :param op_args: Example: (sim_path,m,n,...)
        """
        self.op = op_type(*op_args)
        self.reals = sorted(
            [int(f) for f in os.listdir(self.op.sim_path) if re.findall("^\d+$", f)]).reverse()[:num_realizations]

    def calc_write(self, bin_width=0.2, calc_upper_lower=True):
        # TODO: read exisiting data and save expensive calculation time
        # TODO: implement and send runs see if get clearer data with smart averaging...
        op_type, op_args, numbered_files = self.op_type, self.op_args, self.reals
        op = op_type(*op_args)  # starts with the last realization by default
        op.write(bin_width=bin_width)
        counts, op_corr = op.counts, op.op_corr * op.counts
        if calc_upper_lower:
            lower_counts, upper_counts, lower_op_corr, upper_op_corr = \
                op.lower.counts, op.upper.counts, op.lower.op_corr * op.lower.counts, op.upper.op_corr * op.upper.counts
        op_corr[counts == 0] = 0  # remove nans
        for i in numbered_files[1:]:  # from one before last forward
            op = op_type(*op_args, centers=np.loadtxt(os.path.join(self.sim_path, str(i))), spheres_ind=i)
            op.write(bin_width=bin_width, write_upper_lower=calc_upper_lower)
            counts += op.counts
            if op_type is not PositionalCorrelationFunction:
                I = np.where(op.counts > 0)
                op_corr[I] += op.op_corr[I] * op.counts[I]  # add psi where it is not nan
            if calc_upper_lower:
                lower_counts += op.lower.counts
                upper_counts += op.upper.counts
                if op_type is not PositionalCorrelationFunction:
                    I = np.where(op.lower.counts > 0)
                    lower_op_corr[I] += op.lower.op_corr[I] * op.lower.counts[I]  # add psi where it is not nan
                    I = np.where(op.upper.counts > 0)
                    upper_op_corr[I] += op.upper.op_corr[I] * op.upper.counts[I]  # add psi where it is not nan
        op.spheres_ind = str(numbered_files[-1]) + "-" + str(numbered_files[0])
        op.op_corr = op_corr / counts if op_type is not PositionalCorrelationFunction else counts / np.nanmean(
            counts[np.where(counts > 0)])
        op.counts = counts
        op.op_name = op.op_name + "_" + str(len(numbered_files)) + "_averaged"
        if calc_upper_lower:
            op.lower.op_corr = lower_op_corr / lower_counts if op_type is not PositionalCorrelationFunction else \
                lower_counts / np.nanmean(lower_counts[np.where(lower_counts > 0)])
            op.lower.counts = lower_counts
            op.lower.op_name = op.lower.op_name + "_" + str(len(numbered_files) + 1) + "_averaged"

            op.upper.op_corr = upper_op_corr / upper_counts if op_type is not PositionalCorrelationFunction else \
                upper_counts / np.nanmean(upper_counts[np.where(upper_counts > 0)])
            op.upper.counts = upper_counts
            op.upper.op_name = op.upper.op_name + "_" + str(len(numbered_files) + 1) + "_averaged"
        op.write(bin_width=bin_width, write_vec=False, write_upper_lower=calc_upper_lower)


class BurgerField(OrderParameter):

    @staticmethod
    def name():
        return "burger_vectors"

    def __init__(self, sim_path, a1, a2, psi_op: PsiMN, centers=None, spheres_ind=None, calc_upper_lower=False):
        super().__init__(sim_path, centers, spheres_ind, calc_upper_lower=False)
        self.op_name = BurgerField.name()
        self.psi = psi_op
        self.a1, self.a2 = a1, a2
        if calc_upper_lower:
            upper_centers = [c for c in self.spheres if c[2] >= self.event_2d_cells.boundaries[2] / 2]
            lower_centers = [c for c in self.spheres if c[2] < self.event_2d_cells.boundaries[2] / 2]
            self.upper = BurgerField(sim_path, centers=upper_centers, spheres_ind=self.spheres_ind,
                                     a1=a1 + a2, a2=a1 - a2, psi_op=psi_op.upper)
            self.lower = BurgerField(sim_path, centers=lower_centers, spheres_ind=self.spheres_ind,
                                     a1=a1 + a2, a2=a1 - a2, psi_op=psi_op.lower)
            self.upper.op_name = "upper_burger_vectors"
            self.lower.op_name = "lower_burger_vectors"

    def calc_order_parameter(self, calc_upper_lower=False):
        perfect_lattice_vectors = np.array([n * self.a1 + m * self.a2 for n in range(-3, 3) for m in range(-3, 3)])
        orientation = self.psi.rotate_spheres(calc_spheres=False)
        R = np.array([[np.cos(orientation), -np.sin(orientation)], [np.sin(orientation), np.cos(orientation)]])
        perfect_lattice_vectors = np.array([np.matmul(R, p.T) for p in perfect_lattice_vectors])
        # rotate = lambda ps: np.matmul(R(-orientation), np.array(ps).T).T
        disloc_burger, disloc_location = BurgerField.calc_burger_vector(self.event_2d_cells, perfect_lattice_vectors)
        self.op_vec = np.concatenate((np.array(disloc_location).T, np.array(disloc_burger).T)).T  # x, y, bx, by field
        if calc_upper_lower:
            self.lower.calc_order_parameter()
            self.upper.calc_order_parameter()

    @staticmethod
    def calc_burger_vector(event_2d_cells, perfect_lattice_vectors):
        """
        Calculate the burger vector on each plaquette of the Delaunay triangulation using methods in:
            [1]	https://link.springer.com/content/pdf/10.1007%2F978-3-319-42913-7_20-1.pdf
            [2]	https://www.sciencedirect.com/science/article/pii/S0022509614001331?via%3Dihub
        :param event_2d_cells: Structure containing spheres centers, boundaries ext.
        :param wraped_psi: orientational order parameter for local orientation. psi(i) correspond to the i'th sphere
        :param perfect_lattice_vectors: list of vectors of the perfect lattice. Their magnitude is no important.
        :return: The positions (r) and burger vector at each position b. The position of a dislocation is take as the
                center of the plaquette.
        """
        wraped_centers = BurgerField.wrap_with_boundaries(event_2d_cells, w=5)
        # all spheres within w distance from cyclic boundary will be mirrored
        tri = Delaunay(wraped_centers)
        dislocation_burger = []
        dislocation_location = []
        for i, simplex in enumerate(tri.simplices):
            rc = np.mean(tri.points[simplex], 0)
            if rc[0] < 0 or rc[0] > event_2d_cells.boundaries[0] or rc[1] < 0 or rc[1] > \
                    event_2d_cells.boundaries[1]:
                continue
            b_i = BurgerField.burger_calculation(tri.points[simplex], perfect_lattice_vectors)
            if np.linalg.norm(b_i) > epsilon:
                dislocation_location.append(rc)
                dislocation_burger.append(b_i)
        return dislocation_burger, dislocation_location

    @staticmethod
    def burger_calculation(simplex_points, perfect_lattice_vectors):
        simplex_points = np.array(simplex_points)

        ts = []
        rc = np.mean(simplex_points, 0)
        for p in simplex_points:
            ts.append(np.arctan2(p[0] - rc[0], p[1] - rc[1]))
        I = np.argsort(ts)
        simplex_points = simplex_points[I]  # calculate burger circuit always anti-clockwise
        which_L = lambda x_ab: np.argmin([np.linalg.norm(x_ab - L_) for L_ in perfect_lattice_vectors])
        L_ab = lambda x_ab: perfect_lattice_vectors[which_L(x_ab)]
        Ls = [L_ab(simplex_points[b] - simplex_points[a]) for (a, b) in [(0, 1), (1, 2), (2, 0)]]
        return np.sum(Ls, 0)

    @staticmethod
    def wrap_with_boundaries(event_2d_cells, w):
        centers = np.array(event_2d_cells.all_centers)[:, :2]
        Lx, Ly = event_2d_cells.boundaries[:2]
        x = centers[:, 0]
        y = centers[:, 1]

        sp1 = centers[np.logical_and(x - Lx > -w, y < w), :] + [-Lx, Ly]
        sp2 = centers[y < w, :] + [0, Ly]
        sp3 = centers[np.logical_and(x < w, y < w), :] + [Lx, Ly]
        sp4 = centers[x - Lx > -w, :] + [-Lx, 0]
        sp5 = centers[:, :] + [0, 0]
        sp6 = centers[x < w, :] + [Lx, 0]
        sp7 = centers[np.logical_and(x - Lx > -w, y - Ly > -w), :] + [-Lx, -Ly]
        sp8 = centers[y - Ly > -w, :] + [0, -Ly]
        sp9 = centers[np.logical_and(x < w, y - Ly > -w), :] + [Lx, -Ly]

        wraped_centers = np.concatenate((sp1, sp2, sp3, sp4, sp5, sp6, sp7, sp8, sp9))
        return wraped_centers

    def write(self, write_upper_lower=False):
        super().write(write_correlation=False, write_vec=True, write_upper_lower=False)
        if write_upper_lower:
            self.lower.write()
            self.upper.write()


class BraggStructure(OrderParameter):
    def __init__(self, sim_path, psi_op: PsiMN, centers=None, spheres_ind=None):
        super().__init__(sim_path, centers, spheres_ind, calc_upper_lower=False)
        _, self.spheres = psi_op.rotate_spheres()
        self.op_name = "Bragg_S"
        self.k_peak = None
        self.data = []

    def calc_eikr(self, k):
        return np.exp([1j * (k[0] * r[0] + k[1] * r[1]) for r in self.spheres])

    def S(self, k):
        sum_r = np.sum(self.calc_eikr(k))
        N = len(self.spheres)
        S_ = np.real(1 / N * sum_r * np.conjugate(sum_r))
        self.data.append([k[0], k[1], S_])
        return S_

    def tour_on_circle(self, k_radii, theta=None):
        if theta is None:
            theta_peak = np.arctan2(self.k_peak[1], self.k_peak[0])
            theta = np.mod(theta_peak + np.linspace(0, 1, 101) * 2 * np.pi, 2 * np.pi)
            theta = np.sort(np.concatenate([theta, [np.pi / 4 * x for x in range(8)]]))
        for t in theta:
            self.S(k_radii * np.array([np.cos(t), np.sin(t)]))

    def k_perf(self):
        return 2 * np.pi / np.sqrt(self.event_2d_cells.l_x * self.event_2d_cells.l_y / len(
            self.spheres)) * np.array([1, 1])  # rotate self.spheres by orientation before so peak is at [1, 1]

    def calc_peak(self):
        S = lambda k: -self.S(k)
        self.k_peak, S_peak_m, _, _, _ = fmin(S, self.k_perf(), xtol=0.01 / len(self.spheres), ftol=1.0,
                                              full_output=True)
        self.S_peak = -S_peak_m

    def calc_four_peaks(self):
        S = lambda k: -self.S(k)
        self.four_peaks_k = []
        self.four_peaks_S = []
        k_radii = np.linalg.norm(self.k_perf())
        for theta in [np.pi / 4 + n * np.pi / 2 for n in range(1, 4)]:
            k_perf = k_radii * np.array([np.cos(theta), np.sin(theta)])
            k_peak, S_peak_m, _, _, _ = fmin(S, k_perf, xtol=0.01 / len(self.spheres), ftol=1.0,
                                             full_output=True)

    def write(self, write_vec=True):
        op_vec = self.op_vec
        self.op_vec = np.array(self.data)
        # overrides the usless e^(ikr) vector for writing the important data in self.data, while self.op_corr has
        # already been calculated and saved
        super().write(write_correlation=self.op_corr is not None, write_vec=write_vec, write_upper_lower=False)
        self.op_vec = op_vec

    def calc_order_parameter(self):
        self.calc_peak()
        self.op_vec = self.calc_eikr(self.k_peak)
        k1, k2 = np.linalg.norm(self.k_perf()), np.linalg.norm(self.k_peak)
        m1, m2 = min([k1, k2]), max([k1, k2])
        dm = m2 - m1
        for k_radii in np.linspace(m1 - 10 * dm, m2 + 10 * dm, 12):
            self.tour_on_circle(k_radii)
        self.calc_four_peaks()

    def correlation(self, bin_width=0.2, low_memory=True, randomize=False, realizations=int(1e7), time_limit=2 * day):
        super().correlation(bin_width, False, low_memory, randomize, realizations, time_limit)


class MagneticBraggStructure(BraggStructure):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.op_name = "Bragg_Sm"

    def calc_eikr(self, k):
        # sum_n(z_n*e^(ikr_n))
        # z in [rad,lz-rad]-->z in [-1,1]: (z-lz/2)/(lz/2-rad)
        # For z=rad we have (rad-lz/2)/(lz/2-rad)=-1
        # For z=lz-rad we have (lz-rad-lz/2)/(lz/2-rad)=1.
        rad, lz = 1.0, self.event_2d_cells.l_z
        return np.array(
            [(r[2] - lz / 2) / (lz / 2 - rad) * np.exp(1j * (k[0] * r[0] + k[1] * r[1])) for r in self.spheres])

    def k_perf(self):
        return super(MagneticBraggStructure, self).k_perf() / 2


def if_exist_load(path):
    if os.path.exists(path):
        mat = np.loadtxt(path, dtype=complex)
        return [int(r) for r in mat[:, 0]], [p for p in mat[:, 1]]
    else:
        return [], []


def sort_save(path, reals, psis):
    I = np.argsort(reals)
    reals = np.array(reals)[I]
    psis_mean = np.array(psis)[I]
    np.savetxt(path, np.array([reals, psis_mean]).T)


def psi_mean(m, n, sim_path):
    op_dir = os.path.join(sim_path, "OP")
    if not os.path.exists(op_dir): os.mkdir(op_dir)
    op_name_dir = os.path.join(op_dir, 'psi_' + str(m) + str(n))
    if not os.path.exists(op_name_dir): os.mkdir(op_name_dir)
    psis_path = os.path.join(op_name_dir, 'mean_vs_real.txt')

    load = WriteOrLoad(output_dir=sim_path)

    reals, psis_mean = if_exist_load(psis_path)
    init_time = time.time()
    i = 0
    realizations = load.realizations()
    while time.time() - init_time < 2 * day and i < len(realizations):
        sp_ind = realizations[i]
        if sp_ind in reals: continue
        centers = np.loadtxt(os.path.join(load.output_dir, str(sp_ind)))
        psi = PsiMN(sim_path, m, n, spheres_ind=sp_ind, centers=centers)
        psi.calc_order_parameter()
        reals.append(sp_ind)
        psis_mean.append(np.mean(psi.op_vec))
        i += 1
    sort_save(psis_path, reals, psis_mean)


def main():
    op_input = {'realizations': int(1e10), 'randomize': False, 'time_limit': 2 * day}

    realizations = op_input['realizations']

    prefix = "/storage/ph_daniel/danielab/ECMC_simulation_results3.0/"
    sim_path = os.path.join(prefix, sys.argv[1])
    calc_type = sys.argv[2]
    N = int(re.split('_h=', re.split('N=', sys.argv[1])[1])[0])
    # randomize = N ** 2 > realizations
    op_dir = os.path.join(sim_path, "OP")
    if not os.path.exists(op_dir): os.mkdir(op_dir)
    log = os.path.join(op_dir, "log")
    sys.stdout = open(log, "a")
    print("\n\n\n-----------\nDate: " + str(date.today()) + "\nType: " + calc_type + "\nCorrelation couples: " + str(
        realizations), file=sys.stdout)
    if calc_type == "psi23":
        psi23 = PsiMN(sim_path, 2, 3)
        psi23.calc_order_parameter()
        psi23.write(write_correlation=False, write_vec=True)
        psi23.correlation(**op_input)
        psi23.write()
    if calc_type == "psi14":
        psi14 = PsiMN(sim_path, 1, 4)
        psi14.calc_order_parameter()
        psi14.write(write_correlation=False, write_vec=True)
        psi14.correlation(**op_input)
        psi14.write()
    if calc_type == "psi16":
        psi16 = PsiMN(sim_path, 1, 6)
        psi16.calc_order_parameter()
        psi16.write(write_correlation=False, write_vec=True)
        psi16.correlation(**op_input)
        psi16.write()
    if calc_type == "pos":
        psi23, psi14, psi16 = PsiMN(sim_path, 2, 3), PsiMN(sim_path, 1, 4), PsiMN(sim_path, 1, 6)
        psi23.calc_order_parameter(), psi14.calc_order_parameter(), psi16.calc_order_parameter()
        psis = [psi14, psi23, psi16]
        psis_mean = [psi.op_vec for psi in psis]
        correct_psi = psis[np.argmax(np.abs([np.sum(p) for p in psis_mean]))]
        pos = PositionalCorrelationFunction(sim_path, correct_psi)
        pos.correlation(**op_input)
        pos.write()
    if calc_type == "burger_square":
        load = WriteOrLoad(output_dir=sim_path)
        l_x, l_y, l_z, rad, rho_H, edge, n_row, n_col = load.load_Input()
        a = np.sqrt(l_x * l_y / N)
        a1 = np.array([a, 0])
        a2 = np.array([0, a])

        psi_dir_name = os.path.join(op_dir, 'psi_14')
        if not os.path.exists(psi_dir_name): os.mkdir(psi_dir_name)
        psis_path = os.path.join(psi_dir_name, 'mean_vs_real.txt')
        reals, psis_mean = if_exist_load(psis_path)

        burg_dir = os.path.join(op_dir, BurgerField.name())

        init_time = time.time()
        i = 0
        realizations = load.realizations()
        while time.time() - init_time < op_input['time_limit'] and i < len(realizations):
            sp_ind = realizations[i]
            if os.path.exists(os.path.join(burg_dir, 'vec_' + str(sp_ind) + '.txt')): continue
            centers = np.loadtxt(os.path.join(load.output_dir, str(sp_ind)))
            psi14 = PsiMN(sim_path, 1, 4, spheres_ind=sp_ind, centers=centers)
            psi14.calc_order_parameter()
            burger = BurgerField(sim_path, a1, a2, psi14, spheres_ind=sp_ind, centers=centers)
            burger.calc_order_parameter()
            burger.write()
            reals.append(sp_ind)
            psis_mean.append(np.mean(psi14.op_vec))
            i += 1
        sort_save(psis_path, reals, psis_mean)
    if calc_type.startswith("Bragg_S"):
        init_time = time.time()
        if calc_type.endswith("23"): psi = PsiMN(sim_path, 2, 3)
        if calc_type.endswith("16"): psi = PsiMN(sim_path, 1, 6)
        if calc_type.endswith("14"): psi = PsiMN(sim_path, 1, 4)
        psi.calc_order_parameter()
        if calc_type.startswith("Bragg_Sm"):
            bragg = MagneticBraggStructure(sim_path, psi)
        else:
            bragg = BraggStructure(sim_path, psi)
        bragg.calc_order_parameter()
        bragg.write()
        bragg.correlation(**op_input)
        bragg.write(write_vec=False)
    if calc_type == "psi23mean": psi_mean(2, 3, sim_path)
    if calc_type == "psi14mean": psi_mean(1, 4, sim_path)


if __name__ == "__main__":
    main()
