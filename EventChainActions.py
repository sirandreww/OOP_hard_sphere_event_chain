import numpy as np
import copy
from enum import Enum

from Structure import CubeBoundaries, BoundaryType, ArrayOfCells, Cell, Metric

epsilon = 1e-4


class Step:

    def __init__(self, sphere, total_step, v_hat, boundaries, current_step=np.nan):
        """
        The characteristic of the step to be perform
        :type sphere: Sphere
        :param total_step: total step left for the current move of spheres
        :param current_step: step sphere is about to perform
        :param v_hat: direction of the step
        :type boundaries: CubeBoundaries
        """
        self.sphere = sphere
        self.total_step = total_step
        self.current_step = current_step
        self.v_hat = v_hat
        self.boundaries = boundaries

    def clone(self, current_step=np.nan):
        s = copy.deepcopy(self.sphere)
        if current_step != np.nan:
            return Step(s, self.total_step, self.v_hat, self.boundaries, current_step)
        return Step(s, self.total_step, self.v_hat, self.boundaries, self.current_step)

    def perform_step(self):
        """
        Perform the current step (calls Sphere's perform step), and subtract step from total step
        """
        self.sphere.perform_step(self)
        self.total_step = self.total_step - self.current_step

    @staticmethod
    def next_event(step, other_spheres):
        """
        Returns the next Event object to be handle, such as from the even get the step, perform the step and decide the
        next event
        :type step: Step
        :param other_spheres: other spheres which sphere might collide
        :return: Step object containing the needed information such as step size or step type (wall free or boundary)
        """
        sphere = step.sphere
        total_step = step.total_step
        v_hat = step.v_hat
        min_dist_to_wall, closest_wall = Metric.dist_to_boundary(sphere, total_step, v_hat, self.boundaries)
        closest_sphere = []
        closest_sphere_dist = float('inf')
        for other_sphere in other_spheres:
            sphere_dist = Metric.dist_to_collision(sphere, other_sphere, total_step, v_hat)
            if sphere_dist < closest_sphere_dist:
                closest_sphere_dist = sphere_dist
                closest_sphere = other_sphere

        # it hits a wall
        if min_dist_to_wall < closest_sphere_dist:
            return Event(step.clone(min_dist_to_wall), EventType.WALL, [], closest_wall)

        # it hits another sphere
        if min_dist_to_wall > closest_sphere_dist:
            return Event(step.clone(closest_sphere_dist), EventType.COLLISION, closest_sphere, [])

        # it hits nothing, both min_dist_to_wall and closest_sphere_dist are inf
        return Event(step.clone(total_step), EventType.FREE, [], [])


class EventType(Enum):
    FREE = "FreeStep"  # Free path
    COLLISION = "SphereSphereCollision"  # Path leads to collision with another sphere
    WALL = "RigidWallBoundaryCondition"  # Path reaches rigid wall and needs to be handle


class Event:

    def __init__(self, step, event_type, other_sphere, wall):
        """
        A single event that will happen to sphere, such as collision with another sphere
        or arriving at the boundary of the simulation
        :param step: step to be perform before event
        :type step: Step
        :type event_type: EventType
        :param other_sphere: if event is collision, this is the sphere it will collide
        :type other_sphere: Sphere
        :param wall: if event is boundary condition, this is the wall it is going to reach
        """
        self.step = step
        self.event_type = event_type
        self.other_sphere = other_sphere
        self.wall = wall


class EfficientEventChainCellArray2D(ArrayOfCells):

    def __init__(self, edge, n_rows, n_columns):
        """
        Construct a 2 dimension default choice list of empty cells (without spheres), with constant edge
        :param n_rows: number of rows in the array of cells
        :param n_columns: number of columns in the array of cells
        :param edge: constant edge size of all cells is assumed and needs to be declared
        """
        l_x = edge*n_columns
        l_y = edge*n_columns
        cells = [[[] for _ in range(n_columns)] for _ in range(n_rows)]
        for i in range(n_rows):
            for j in range(n_columns):
                site = [edge*i, edge*j]
                cells[i][j] = Cell(site, [edge, edge], ind=(i, j))
        boundaries = CubeBoundaries([l_x, l_y], [BoundaryType.CYCLIC, BoundaryType.CYCLIC])
        super().__init__(2, boundaries, cells=cells)
        self.edge = edge
        self.n_rows = n_rows
        self.n_columns = n_columns

    def closest_site_2d(self, point):
        """
        Solve for closest site to point, in 2d, assuming all cells edges have the same length edge
        :return: tuple (i,j) of the closest cell = cells[i][j]
        """
        i = round(point[1] % self.edge) % self.n_rows
        j = round(point[0] % self.edge) % self.n_columns
        return i, j

    def relevant_cells_around_point_2d(self, rad, point):
        """
        Finds cells which a sphere with radius rad with center at point would have overlap with
        :param rad: radius of interest
        :param point: point around which we find cells
        :return: list of cells with overlap with
        """
        lx = self.boundaries.edges[0]
        ly = self.boundaries.edges[1]
        i, j = self.closest_site_2d(point)
        cells = self.cells
        a = cells[i][j]
        b = cells[i - 1][j]
        c = cells[i - 1][j - 1]
        d = cells[i][j - 1]
        dx, dy = np.array(point)-cells[i][j].site

        #Boundaries:
        e = self.edge
        if dx > e: dx = dx - lx
        if dy > e: dy = dy - ly
        if dx < -e: dx = lx + dx
        if dy < -e: dy = ly + dy

        # cases for overlap
        if dx > rad and dy > rad:  # 0<theta<90  # 1
            return [a]
        if dx > rad and abs(dy) <= rad:  # 0=theta  # 2
            return [a, b]
        if dx > rad and dy < -rad:  # -90<theta<0  # 3
            return [b]
        if abs(dx) <= rad and dy < -rad:  # theta=-90  # 4
            return [b, c]
        if dx < -rad and dy < -rad:  # -180<theta<-90  # 5
            return [c]
        if dx < -rad and abs(dy) <= rad:  # theta=180  # 6
            return [c, d]
        if dx < -rad and dy > rad:  # 90<theta<180  # 7
            return [d]
        if abs(dx) <= rad and dy > rad:  # theta=90  # 8
            return [a, d]
        else:  # abs(dx) <= rad and abs(dy) <= rad:  # x=y=0  # 9
            return [a, b, c, d]

    def get_all_crossed_points_2d(self, sphere, total_step, v_hat):
        """
        :type sphere: Sphere
        :param sphere: sphere about to perform step
        :param total_step: total length of step that might be performed
        :param v_hat: direction of step
        :return: list of ts such that trajectory(t) is a point crossing cell boundary
        """
        vx = np.dot(v_hat, [1, 0])
        vy = np.dot(v_hat, [0, 1])
        ts = [0]
        len_v = sphere.systems_length_in_v_direction(v_hat, self.boundaries)
        for starting_point, _ in sphere.trajectories_braked_to_lines(total_step, v_hat, self.boundaries)[:-1]:
            # [-1]=end point
            if vy != 0:
                for i in range(self.n_rows):
                    y = i * self.edge
                    t = (y - np.dot(starting_point, [0, 1])) / vy
                    if t < 0: t = t + len_v
                    ts.append(t)
            if vx != 0:
                for j in range(self.n_columns):
                    x = j*self.edge
                    t = (x - np.dot(starting_point, [1, 0])) / vx
                    if t < 0: t = t + len_v
                    ts.append(t)
        return np.sort([t for t in ts if t <= total_step])

    def perform_total_step(self, cell_ind, sphere, total_step, v_hat):
        """
        Perform step for all the spheres, starting from sphere inside cell which is at cells[cell_ind]
        :param cell_ind: (i,j,...)
        :type cell_ind: tuple
        :type sphere: Sphere
        :param total_step: total step left to perform
        :param v_hat: direction of step
        """
        cell = self.cell_from_ind(cell_ind)
        cell.remove(sphere)
        cells = []
        sub_cells = []
        for t in self.get_all_crossed_points_2d(sphere, total_step, v_hat):
            previous_sub_cells = sub_cells
            sub_cells = []
            for c in self.relevant_cells_around_point_2d(sphere.rad, sphere.trajectory(t, v_hat, self.boundaries)):
                if c not in previous_sub_cells:
                    sub_cells.append(c)
            cells.append(sub_cells)
        step = Step(sphere, total_step, v_hat, self.boundaries)
        for i, sub_cells in enumerate(cells):
            other_spheres = []
            for c in sub_cells:
                for s in c.spheres: other_spheres.append(s)
            event = step.next_event(sphere, other_spheres)  # calculate current step and update step
            if event.event_type != EventType.FREE:
                if i == len(cells)-1: break
                else:
                    next_other_spheres = []
                    for next_cell in cells[i+1]:
                        for s in next_cell.spheres: next_other_spheres.append(s)
                    another_potential_event = step.next_event(next_other_spheres)
                    if event.step.current_step > another_potential_event.step.current_step:
                        event = another_potential_event
                        sub_cells = cells[i+1]
                    break
        event.step.perform_step(event.step, self.boundaries)  # subtract total step
        for new_cell in sub_cells:
            if new_cell.should_sphere_be_in_cell(sphere):
                new_cell.add_sphere(sphere)
                break
        if event.event_type == EventType.COLLISION:
            self.perform_step(new_cell.ind, event.other_sphere, event.step.total_step)
        if event.event_type == EventType.WALL:
            event.step.v_hat = CubeBoundaries.flip_v_hat_wall_part(event.wall, sphere, v_hat)
            self.perform_step(new_cell.ind, sphere, event.step.total_step)
        if event.event_type == EventType.FREE:
            return
