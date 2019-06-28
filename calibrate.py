#!/usr/bin/env python

from __future__ import print_function, division
import sys
import os.path
from copy import copy
import time
import itertools
import argparse
import xml.etree.ElementTree as ET
import csv
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import PyKDL
import rospy
import dvrk
from analyze_data import get_new_offset, get_best_fit
from marker import Marker
from cisstNumericalPython import nmrRegistrationRigid
# from rot_matrix_test import *


class Calibration:

    ROT_MATRIX = PyKDL.Rotation(
        1,    0,    0,
        0,   -1,    0,
        0,    0,   -1
    )

    ROT_MATRIX_NP = np.array([
        [1,    0,    0],
        [0,   -1,    0],
        [0,    0,   -1]
    ])

    def __init__(self, robot_name, polaris=False):
        print("initializing calibration for", robot_name)
        print("have a flat surface below the robot")
        self.data = []
        self.info = {}
        # Add checker for directory

        self.arm = dvrk.arm(robot_name)
        self.home()
        if polaris:
            self.marker = Marker()
            self.polaris = True
        else:
            self.polaris = False

    def home(self):
        "Goes to x = 0, y = 0, extends joint 2 past the cannula, and sets home"
        # make sure the camera is past the cannula and tool vertical
        print("starting home")
        self.arm.home()
        goal = np.copy(self.arm.get_current_joint_position())
        if ((self.arm.name() == 'PSM1') or (self.arm.name() == 'PSM2') or
            (self.arm.name() == 'PSM3') or (self.arm.name() == 'ECM')):
            # set in position joint mode
            goal[0] = 0.0
            goal[1] = 0.0
            goal[2] = 0.12
            self.arm.move_joint(goal)
        self.arm.move(self.ROT_MATRIX)

    def get_corners(self):
        "Gets input from user to get three corners of the plane"
        pts = []
        raw_input("Hello. Pick the first corner, then press enter. ")
        pts.append(self.arm.get_current_position())
        raw_input("Pick the second corner, then press enter. ")
        pts.append(self.arm.get_current_position())
        raw_input("Pick the third corner, then press enter. ")
        pts.append(self.arm.get_current_position())
        return pts

    def record_points(self, pts, nsamples, verbose=False):
        """Moves in a zig-zag pattern in a grid and records the points
        at which the arm reaches the surface"""
        if not len(pts) == 3:
            return False
        
        self.info["points"] = [pt.p for pt in pts]
        self.info["polaris"] = False
        
        # horiz is the line that is horizontal
        # if abs((pts[1].p - pts[0].p)[2]) < abs((pts[2].p - pts[1].p)[2]):
        #     p1 = pts[0].p
        # else:
        #     p1 = pts[2].p
        # p2 = pts[1].p

        # roll = np.arccos(abs((p2 - p1)[0]) / np.sqrt(np.square((p2 - p1)[1])
        #                                              + np.square((p2 - p1)[0])))
        
        # offset_rot = rot_matrix(0, 0, 0)
        # new_rot_np = offset_rot.dot(self.ROT_MATRIX_NP)
        # new_rot_kdl = np2kdl(new_rot_np)

        THRESH = 1.5
        initial = PyKDL.Frame()
        initial.p = copy(pts[2].p)
        initial.M = self.ROT_MATRIX
        initial.p[2] += 0.05
        self.arm.move(initial)

        final = PyKDL.Frame()
        final.p = copy(pts[0].p)
        final.M = self.ROT_MATRIX
        final.p[2] += 0.05

        self.arm.move(final)

        goal = PyKDL.Frame(self.ROT_MATRIX)
        # goal = PyKDL.Frame(new_rot_kdl)

        # if verbose:
        #     print(np.rad2deg(roll))
        print("Using points {}, {}, and {}".format(*[tuple(pt.p) for pt in pts]))

        for i in range(nsamples):
            rightside = pts[1].p + i / (nsamples - 1) * (pts[2].p - pts[1].p)
            leftside = pts[0].p + i / (nsamples - 1) * (pts[2].p - pts[1].p)
            print("moving arm to row ", i)
            for j in range(nsamples):
                print("\tmoving arm to column ", j)
                if i % 2 == 0:
                    goal.p = leftside + (j / (nsamples - 1) *
                                         (rightside - leftside))
                else:
                    goal.p = rightside + (j / (nsamples - 1) *
                                          (leftside - rightside))
                prev_goal = copy(goal)
                goal.p[2] += 0.01
                self.arm.move(goal)

                for k in range(20): # in millimeters
                    goal.p[2] -= 0.001
                    self.arm.move(goal)
                    force = self.arm.get_current_wrench_body()[2]
                    force
                    if abs(force) >= THRESH:
                        goal.p[2] += 0.001
                        break
                    elif k == 19:
                        print("Error: Did not reach surface at row {}, "
                              "column {}".format(i, j))
                        sys.exit(1)

                for k in range(20): # In tenths of a millimeter
                    goal.p[2] -= 0.0001
                    self.arm.move(goal)
                    if abs(self.arm.get_current_wrench_body()[2]) >= THRESH:
                        dist = (prev_goal.p -
                            self.arm.get_current_position().p)[2]
                        self.data.append(
                            list(self.arm.get_current_position().p) +
                            list(self.arm.get_current_joint_position())
                        )
                        if verbose:
                            print("Distance: %fmm" % (dist * 1000))
                            print(prev_goal.p)
                        goal.p[2] = prev_goal.p[2]
                        break
                    elif k == 19:
                        print("Error: Did not reach surface when rechecking "
                              "at row {}, column {}".format(i, j))
                        sys.exit(1)
                        

                goal.p[2] += 0.01
                self.arm.move(goal)
                # move down until forces acts upon the motor

                
                time.sleep(0.5)
        print(rospy.get_caller_id(), '<- calibration complete')
    
    def record_points_polaris(self, pts, nsamples, verbose=False):
        """Moves in a zig-zag pattern in a grid and records the points
        at which the arm reaches the surface"""
        if not len(pts) == 3:
            return False

        self.info["points"] = [pt.p for pt in pts]
        self.info["polaris"] = True

        initial = PyKDL.Frame()
        initial.p = copy(pts[2].p)
        initial.M = self.ROT_MATRIX
        initial.p[2] += 0.05
        self.arm.move(initial)

        final = PyKDL.Frame()
        final.p = copy(pts[0].p)
        final.M = self.ROT_MATRIX
        final.p[2] += 0.05

        self.arm.move(final)

        goal = PyKDL.Frame(self.ROT_MATRIX)

        if verbose:
            print("Using points {}, {}, and {}".format(*[tuple(pt.p) for pt in pts]))

        for i in range(nsamples):
            rightside = pts[1].p + i / (nsamples - 1) * (pts[2].p - pts[1].p)
            leftside = pts[0].p + i / (nsamples - 1) * (pts[2].p - pts[1].p)
            print("moving arm to row ", i)
            for j in range(nsamples):
                print("\tmoving arm to column ", j)
                if i % 2 == 0:
                    goal.p = leftside + (j / (nsamples - 1) *
                                         (rightside - leftside))
                else:
                    goal.p = rightside + (j / (nsamples - 1) *
                                          (leftside - rightside))
                goal.M = self.ROT_MATRIX
                self.arm.move(goal)
                time.sleep(0.5)
                m = list(self.marker.get_current_position())
                if verbose:
                    print(m)
                self.data.append(
                    m +
                    list(self.arm.get_current_joint_position()) +
                    list(self.arm.get_current_position().p)
                )
                
                time.sleep(0.5)
        print(self.marker.n_bad_callbacks)
        print(rospy.get_caller_id(), '<- calibration complete')
    
    def record_any_points_polaris

    def output_to_csv(self, fpath):
        "Outputs contents of self.data to fpath"
        with open(choose_filename(fpath), 'w') as csvfile:
            info_text = " ".join([
                "{}: {}".format(key, value)
                for (key, value) in self.info.iteritems()
            ])
                
            csvfile.write("# INFO: {}\n".format(info_text))
            writer = csv.writer(
                csvfile, delimiter=',',
                quotechar='"', quoting=csv.QUOTE_MINIMAL
            )
            for row in self.data:
                writer.writerow(row)


def choose_filename(fpath):
    """checks if file at fpath already exists.
    If so, it increments the file"""
    if not os.path.exists(fpath):
        new_fname = fpath
    else:
        fname, file_ext = os.path.splitext(fpath)
        i = 1
        new_fname = "{}_{}{}".format(fname, i, file_ext)
        while os.path.exists(new_fname):
            i += 1
            new_fname = "{}_{}{}".format(fname, i, file_ext)
    return new_fname


def plot_data(data_file):
    "Plots the data from the csv file data_file"
    coords = np.array([])

    polaris_coords = np.array([])

    joints = np.array([])

    with open(data_file, 'r') as csvfile:
        csvfile.readline()
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) == 12:
                polaris = True
            else:
                polaris = False
            joints = np.append(
                joints,
                np.array([float(x) for x in row[3:9]])
            )
            coords = np.append(
                coords,
                np.array([float(x) for x in row[:3]])
            )
            if polaris:
                polaris_coords = np.append(
                    polaris_coords,
                    np.array([float(x) for x in row[9:12]])
                )
    coords = coords.reshape(-1, 3)
    
    if polaris:
        polaris_coords = polaris_coords.reshape(-1, 3)

    joints = joints.reshape(-1, 6)


    if polaris:
        transf, error = nmrRegistrationRigid(coords, polaris_coords)
        rot_matrix = transf.Rotation()
        translation = transf.Translation()
        polaris_coords = (polaris_coords - translation).dot(rot_matrix)
        print("Rigid Registration Error: {}".format(error))


    X, Y = np.meshgrid(
        np.arange(
            min(coords[:,0])-0.05,
            max(coords[:,0])+0.05,
            0.05
        ),
        np.arange(
            min(coords[:,1])-0.05,
            max(coords[:,1])+0.05,
            0.05
        )
    )

    A, B, C = get_best_fit(coords)
    Z = A*X + B*Y + C

    # plot points and fitted surface
    fig = plt.figure()
    ax = fig.gca(projection='3d')
    ax.plot_surface(X, Y, Z, rstride=1, cstride=1, alpha=0.2)
    if polaris:
        ax.scatter(polaris_coords[:,0], polaris_coords[:,1], polaris_coords[:,2],
            c='b', s=20)
    ax.scatter(coords[:,0], coords[:,1], coords[:,2], c='r', s=20)
    plt.xlabel('X')
    plt.ylabel('Y')
    ax.set_zlabel('Z')
    plt.show()


def parse_record(args):
    pts = [
        PyKDL.Vector(0.04969137179347108, 0.12200283317260341, -0.19149147092692725),
        PyKDL.Vector(0.09269885200354012, -0.06284151552138104, -0.1977706048728867),
        PyKDL.Vector(-0.06045055029036737, -0.09093816039641696, -0.19326454699986603)
    ]
    pts = [PyKDL.Frame(Calibration.ROT_MATRIX, pt) for pt in pts]
    if args.polaris:
        calibration = Calibration(args.arm, polaris=True)
        # pts = calibration.get_corners()
        calibration.record_points_polaris(pts, args.samples, verbose=args.verbose)
    else:
        calibration = Calibration(args.arm)
        # pts = calibration.get_corners()

        calibration.record_points(pts, args.samples, verbose=args.verbose)

    calibration.output_to_csv(args.output)


def parse_view(args):
    plot_data(args.input)


def parse_analyze(args):
    offset = 1000 * get_new_offset(args.input, args.output)
    if args.write:
        if os.path.exists(args.write):
            print("Writing offset...")
            tree = ET.parse(args.write)
            root = tree.getroot()
            current_offset = float(root[0][2][2][1].attrib["Offset"])
            # Write to <Config><Robot><Actuator ActuatorID=2>
            #              <AnalogIn><VoltstoPosSI> Offset
            root[0][2][2][1].attrib["Offset"] = str(offset + 
                current_offset)
            tree.write(args.write)
            print(("Wrote offset: {}mm (Current offset) + {}mm (Additional offset) "
                   "= {}mm (Written offset)").format(current_offset, offset,
                                                   offset + current_offset))
        else:
            print("Error: File does not exist")
            sys.exit(1)
    else:
        print("Offset: {}mm".format(offset))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-v", "--verbose",
        help="make output verbose", action="store_true"
    )

    subparser = parser.add_subparsers(title="subcommands")

    parser_record = subparser.add_parser(
        "record",
        help="record data for calibration"
    )
    parser_record.add_argument(
        "arm",
        help="arm to record points from"
    )
    parser_record.add_argument(
        "-o", "--output",
        help="output recorded points "
        "(filename automatically increments)",
        default="data/data.csv"
    )
    parser_record.add_argument(
        "-p", "--polaris",
        help="use polaris",
        default=False,
        action="store_true"
    )
    parser_record.add_argument(
        "-n", "--samples",
        help="number of samples per row "
        "(10 is recommended to get higher quality data)",
        default=10,
        type=int,
    )
    parser_record.set_defaults(func=parse_record)

    parser_view = subparser.add_parser("view", help="view outputted data")
    parser_view.add_argument(
        "input", help="data to read from",
        nargs='?', default="data/data.csv"
    )
    parser_view.set_defaults(func=parse_view)

    parser_analyze = subparser.add_parser(
        "analyze",
        help="analyze outputted data and find offset"
    )
    parser_analyze.add_argument(
        "input",
        help="data to read from",
        nargs='?',
        default="data/data.csv"
    )
    parser_analyze.add_argument(
        "-o", "--output",
        help="output for the graph of offset versus error "
        "(filename automatically increments)",
        default="data/error_fk.csv"
    )
    parser_analyze.add_argument(
        "-n", "--no-output",
        help="do not output graph of offset versus error",
        default=False,
        action="store_true"
    )
    parser_analyze.add_argument(
        "-w", "--write",
        help="write offset to file",
        default=False,
    )
    parser_analyze.set_defaults(func=parse_analyze)

    args = parser.parse_args()
    args.func(args)

