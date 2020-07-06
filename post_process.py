import numpy as np
from SnapShot import *
from Structure import *
from EventChainActions import *
from sklearn.neighbors import *
import os


class OrderParameter:

    def __init__(self, sim_path, centers=None, spheres_ind=None):
        self.sim_path = sim_path
        write_or_load = WriteOrLoad(sim_path)
        l_x, l_y, l_z, rad, rho_H, edge, n_row, n_col = write_or_load.load_Input()
        self.event_2d_cells = Event2DCells(edge, n_row, n_col)
        self.event_2d_cells.add_third_dimension_for_sphere(l_z)
        if centers is None or spheres_ind is None:
            centers, spheres_ind = write_or_load.last_spheres()
        self.spheres_ind = spheres_ind
        self.event_2d_cells.append_sphere([Sphere(c, rad) for c in centers])
        self.write_or_load = WriteOrLoad(sim_path, self.event_2d_cells.boundaries)
        self.N = len(centers)

        self.op_vec = None
        self.op_corr = None
        self.corr_centers = None
        self.counts = None

        self.op_name = "phi"

    def calc_order_parameter(self):
        """to be override by child class"""
        self.op_vec = [not None for _ in range(self.N)]
        pass

    def correlation(self, bin_width=0.1):
        if self.op_vec is None: self.calc_order_parameter()

        phiphi_vec = (np.conj(np.transpose(np.matrix(self.op_vec))) *
                      np.matrix(self.op_vec)).reshape((len(self.op_vec) ** 2,))
        x = np.array([r[0] for r in self.event_2d_cells.all_centers])
        y = np.array([r[1] for r in self.event_2d_cells.all_centers])
        dx = (x.reshape((len(x), 1)) - x.reshape((1, len(x)))).reshape(len(x) ** 2, )
        dy = (y.reshape((len(y), 1)) - y.reshape((1, len(y)))).reshape(len(y) ** 2, )
        lx, ly = self.event_2d_cells.boundaries.edges[:2]
        dx = np.minimum(np.abs(dx), np.minimum(np.abs(dx + lx), np.abs(dx - lx)))
        dy = np.minimum(np.abs(dy), np.minimum(np.abs(dy + ly), np.abs(dy - ly)))
        pairs_dr = np.sqrt(dx ** 2 + dy ** 2)

        I = np.argsort(pairs_dr)
        pairs_dr = pairs_dr[I]
        phiphi_vec = phiphi_vec[0, I]

        centers = np.linspace(0, np.max(pairs_dr), int(np.max(pairs_dr) / bin_width) + 1) + bin_width / 2
        counts = np.zeros(len(centers))
        phiphi_hist = np.zeros(len(centers), dtype=np.complex)
        i = 0
        for j in range(len(pairs_dr)):
            if pairs_dr[j] > centers[i] + bin_width / 2:
                i += 1
            phiphi_hist[i] += phiphi_vec[0, j]
            counts[i] += 1
        I = np.where(np.logical_and(counts != 0, phiphi_hist != np.nan))
        self.counts = counts[I]
        self.op_corr = np.real(phiphi_hist[I]) / counts + 1j * np.imag(phiphi_hist[I]) / counts
        self.corr_centers = centers[I]

    def calc_write(self, calc_correlation=True, bin_width=0.1, write_vec=True):
        f = lambda a, b: os.path.join(a, b)
        g = lambda name, mat: np.savetxt(
            f(f(self.sim_path, "OP"), self.op_name + "_" + name + "_" + str(self.spheres_ind)) + ".txt", mat)
        if not os.path.exists(f(self.sim_path, "OP")): os.mkdir(f(self.sim_path, "OP"))
        if self.op_name != "phi" and write_vec:
            if self.op_vec is None: self.calc_order_parameter()
            g("vec", self.op_vec)
        if calc_correlation:
            if self.op_corr is None: self.correlation(bin_width=bin_width)
            g("correlation", np.transpose([self.corr_centers, np.abs(self.op_corr), self.counts]))


class PsiMN(OrderParameter):

    def __init__(self, sim_path, m, n, centers=None, spheres_ind=None):
        super().__init__(sim_path, centers, spheres_ind)
        self.m, self.n = m, n
        upper_centers = [c for c in self.event_2d_cells.all_centers if
                         c[2] >= self.event_2d_cells.boundaries.edges[2] / 2]
        lower_centers = [c for c in self.event_2d_cells.all_centers if
                         c[2] < self.event_2d_cells.boundaries.edges[2] / 2]
        self.lower = OrderParameter(sim_path, lower_centers, self.spheres_ind)
        self.upper = OrderParameter(sim_path, upper_centers, self.spheres_ind)

        self.op_name = "psi_" + str(self.m) + str(self.n)
        self.upper.op_name = "upper_psi_1" + str(self.n * self.m)
        self.lower.op_name = "lower_psi_1" + str(self.n * self.m)

    @staticmethod
    def psi_m_n(event_2d_cells, m, n):
        centers = event_2d_cells.all_centers
        sp = event_2d_cells.all_spheres
        cyc_bound = CubeBoundaries(event_2d_cells.boundaries.edges[:2], 2 * [BoundaryType.CYCLIC])
        cyc = lambda p1, p2: Metric.cyclic_dist(cyc_bound, Sphere(p1, 1), Sphere(p2, 1))
        graph = kneighbors_graph([p[:2] for p in centers], n_neighbors=n, metric=cyc)
        psimn_vec = np.zeros(len(centers), dtype=np.complex)
        for i in range(len(centers)):
            sp[i].nearest_neighbors = [sp[j] for j in graph.getrow(i).indices]
            dr = [np.array(centers[i]) - s.center for s in sp[i].nearest_neighbors]
            t = np.arctan2([r[1] for r in dr], [r[0] for r in dr])
            psi_n = np.mean(np.exp(1j * n * t))
            psimn_vec[i] = np.abs(psi_n) * np.exp(1j * m * np.angle(psi_n))
        return psimn_vec, graph

    def calc_order_parameter(self):
        self.op_vec, _ = PsiMN.psi_m_n(self.event_2d_cells, self.m, self.n)
        self.lower.op_vec, _ = PsiMN.psi_m_n(self.lower.event_2d_cells, 1, self.m * self.n)
        self.upper.op_vec, _ = PsiMN.psi_m_n(self.upper.event_2d_cells, 1, self.m * self.n)

    def calc_write(self, calc_correlation=True, bin_width=0.1):
        super().calc_write(calc_correlation, bin_width)
        self.lower.calc_write(calc_correlation, bin_width)
        self.upper.calc_write(calc_correlation, bin_width)
        np.savetxt(os.path.join(os.path.join(self.sim_path, "OP"), "lower_" + str(self.spheres_ind) + ".txt"),
                   self.lower.event_2d_cells.all_centers)
        np.savetxt(os.path.join(os.path.join(self.sim_path, "OP"), "upper_" + str(self.spheres_ind) + ".txt"),
                   self.upper.event_2d_cells.all_centers)


class PositionalCorrelationFunction(OrderParameter):

    def __init__(self, sim_path, theta=0, rect_width=0.1, centers=None, spheres_ind=None):
        super().__init__(sim_path, centers, spheres_ind)
        self.theta = theta
        self.rect_width = rect_width
        self.op_name = "positional_theta=" + str(theta)

    def correlation(self, bin_width=0.1):
        theta, rect_width = self.theta, self.rect_width
        v_hat = np.transpose(np.matrix([np.cos(theta), np.sin(theta)]))

        x = np.array([r[0] for r in self.event_2d_cells.all_centers])
        y = np.array([r[1] for r in self.event_2d_cells.all_centers])
        dx = (x.reshape((len(x), 1)) - x.reshape((1, len(x)))).reshape(len(x) ** 2, )
        dy = (y.reshape((len(y), 1)) - y.reshape((1, len(y)))).reshape(len(y) ** 2, )
        lx, ly = self.event_2d_cells.boundaries.edges[:2]
        A = np.transpose([dx, dx + lx, dx - lx])
        I = np.argmin(np.abs(A), axis=1)
        J = [i for i in range(len(I))]
        dx = A[J, I]
        A = np.transpose([dy, dy + ly, dy - ly])
        I = np.argmin(np.abs(A), axis=1)
        dy = A[J, I]

        pairs_dr = np.transpose([dx, dy])

        dist_vec = np.transpose(v_hat * np.transpose(pairs_dr * v_hat) - np.transpose(pairs_dr))
        dist_to_line = np.linalg.norm(dist_vec, axis=1)
        I = np.where(dist_to_line <= rect_width)[0]
        pairs_dr = pairs_dr[I]
        J = np.where(pairs_dr * v_hat > 0)[0]
        pairs_dr = pairs_dr[J]
        rs = pairs_dr * v_hat
        l = np.sqrt(lx ** 2 + ly ** 2)

        binds_edges = np.linspace(0, int(l / bin_width) * bin_width, int(l / bin_width) + 1)
        self.counts, _ = np.histogram(rs, binds_edges)
        self.corr_centers = binds_edges[:-1] + bin_width / 2
        self.op_corr = self.counts / np.nanmean(self.counts[np.where(self.counts > 0)])

    def calc_write(self, calc_correlation=True, bin_width=0.1, write_vec=True):
        super().calc_write(calc_correlation, bin_width, write_vec=False)


class RealizationsAveragedOP:
    def __init__(self, num_realizations, op_type, op_args, bin_width=0.1):
        """

        :type sim_path: str
        :type num_realizations: int
        :param op_type: OrderParameter. Example: op_type = PsiMn
        :param op_args: Example: (sim_path,m,n,...)
        """
        self.sim_path = op_args[0]
        files = os.listdir(self.sim_path)
        numbered_files = sorted([int(f) for f in files if re.findall("^\d+$", f)])
        numbered_files.reverse()
        numbered_files = numbered_files[1:num_realizations]  # from one before last forward
        op = op_type(*op_args)  # starts with the last realization by default
        op.calc_write(bin_width=bin_width)
        counts, op_corr = op.counts, op.op_corr * op.counts
        for i in numbered_files:
            op = op_type(*op_args, centers=np.loadtxt(os.path.join(self.sim_path, str(i))), spheres_ind=i)
            op.calc_write()
            counts += op.counts
            op_corr += op.op_corr * op.counts
        op.op_corr = op_corr / op.counts if op_type is not PositionalCorrelationFunction else op.counts / np.nanmean(
            op.counts[np.where(op.counts > 0)])
        op.counts = counts
        op.op_name = op.op_name + "_" + str(num_realizations) + "_averaged"
        op.calc_write(bin_width)
