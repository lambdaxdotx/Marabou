import sys
import os
import time

import keras2onnx
import tensorflow as tf
from maraboupy import MarabouNetworkONNX
from maraboupy import MarabouCore
from maraboupy import MarabouUtils
from maraboupy import Marabou
from tensorflow.keras import datasets, layers, models
import numpy as np
import logging
import matplotlib.pyplot as plt
from enum import Enum, auto
import json
import random
import itertools
from tensorflow.keras.models import load_model

import copy

####                     _ _ _                     ____  _     _           _
####     /\             (_) (_)                   / __ \| |   (_)         | |
####    /  \  _   ___  ___| |_  __ _ _ __ _   _  | |  | | |__  _  ___  ___| |_ ___
####   / /\ \| | | \ \/ / | | |/ _` | '__| | | | | |  | | '_ \| |/ _ \/ __| __/ __|
####  / ____ \ |_| |>  <| | | | (_| | |  | |_| | | |__| | |_) | |  __/ (__| |_\__ \
#### /_/    \_\__,_/_/\_\_|_|_|\__,_|_|   \__, |  \____/|_.__/| |\___|\___|\__|___/
####                                       __/ |             _/ |
####                                      |___/             |__/   

#All Policies inherit from this class
class PolicyBase:

    def __init__(self, ds):
        self.policy = None
        self.geometricStepSize = 10
        self.startWith = 0
        self.geometricFactor = 2
        self.ds = DataSet(ds)
        self.coi = True

    # Return output indices of a model sorted according to score in an ascending order.
    def sortByScore(model, score):
        score = CnnAbs.flattenTF(score)        
        assert score.shape == model.outputVars.shape
        return model.outputVars.flatten()[np.argsort(score)]

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        raise NotImplementedError
    
    #Generate refinemnet step sizes.        
    def steps(self, n):
        return self.geometricStep(n)

    #Generate refinemnet step sizes - geometric increasment.
    def geometricStep(self, n, factor=2):
        stepSize = max(self.geometricStepSize, 1)
        startWith = max(self.startWith, 0)
        size = n
        yield startWith
        size -= startWith
        i = 0
        while size > 0:
            toAdd = min(size, self.geometricStepSize * (factor ** i))
            yield toAdd
            size -= toAdd
            i += 1
    
#Policy - Most important neurons are the center of the image.
class PolicyCentered(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)
        self.policy = Policy.Centered

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        assert len(absLayerPredictions.shape) == 4
        absLayerShape = absLayerPredictions.shape[1:]
        corMeshList = np.meshgrid(*[np.arange(d) for d in absLayerShape], indexing='ij')
        center = [(float(d)-1) / 2 for d in absLayerShape]
        distance = np.linalg.norm(np.array([cor - cent for cor, cent in zip(corMeshList, center)]), axis=0)
        score = -distance
        return PolicyBase.sortByScore(modelUpToAbsLayer, score)


#Policy - Refine stepsize most activated neurons, calculating activation on the entire Mnist test.    
class PolicyAllSamplesRank(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)
        self.policy = Policy.AllSamplesRank

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        score = np.mean(absLayerPredictions, axis=0)
        return PolicyBase.sortByScore(modelUpToAbsLayer, score)

#Policy - Refine stepsize most activated neurons, calculating activation on the Mnist test examples labeled the same as prediction label.    
class PolicySingleClassRank(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)
        self.policy = Policy.SingleClassRank

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):        
        score = np.mean(np.array([alp for alp, label in zip(absLayerPredictions, self.ds.y_test) if label == property.yMax]), axis=0)
        return PolicyBase.sortByScore(modelUpToAbsLayer, score)
    
#Policy - calculate per class
class PolicyMajorityClassVote(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)  
        self.policy = Policy.MajorityClassVote  

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        actByClasses = np.array([np.mean(np.array([alp for alp,y in zip(absLayerPredictions, self.ds.y_test) if y == label]), axis=0) for label in range(self.ds.num_classes)])
        score = np.linalg.norm(actByClasses, axis=0)
        return PolicyBase.sortByScore(modelUpToAbsLayer, score)
    
#Policy - Add neurons randomly. 
class PolicyRandom(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)  
        self.policy = Policy.Random  

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        return np.random.permutation(modelUpToAbsLayer.outputVars)

#Policy - No abstraction.
class PolicyVanilla(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)
        self.policy = Policy.Vanilla
        self.coi = False

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        raise NotImplementedError

#Policy - Rank According to activation values of single sample
class PolicySampleRank(PolicyBase):
    
    def __init__(self, ds):
        super().__init__(ds)
        self.policy = Policy.SampleRank

    # Rank abstract layer neurons in according to specific policy. Return neuron indices in ascending order according to rank.        
    def rankAbsLayer(self, modelUpToAbsLayer, property, absLayerPredictions):
        score = np.abs(absLayerPredictions[property.xAdvIndex])
        return PolicyBase.sortByScore(modelUpToAbsLayer, score)
    
# Enum defining the policies
class Policy(Enum):
    Centered          = 0
    AllSamplesRank    = 1
    SingleClassRank   = 2
    MajorityClassVote = 3
    Random            = 4
    Vanilla           = 5    
    SampleRank        = 6

    @staticmethod
    def abstractionPolicies():
        return [policy.name for policy in Policy if policy is not Policy.Vanilla]

    @staticmethod
    def allPolicies():
        return [policy.name for policy in Policy]

    @staticmethod
    def fromString(s, ds):
        s = s.lower()
        if   s == Policy.Centered.name.lower():
            return PolicyCentered(ds)
        elif s == Policy.AllSamplesRank.name.lower():
            return PolicyAllSamplesRank(ds)
        elif s == Policy.SingleClassRank.name.lower():
            return PolicySingleClassRank(ds)
        elif s == Policy.MajorityClassVote.name.lower():
            return PolicyMajorityClassVote(ds)
        elif s == Policy.Random.name.lower():
            return PolicyRandom(ds)
        elif s == Policy.Vanilla.name.lower():
            return PolicyVanilla(ds)
        elif s == Policy.SampleRank.name.lower():
            return PolicySampleRank(ds)
        else:
            raise NotImplementedError

# Adversarial property object.        
class AdversarialProperty:
    def __init__(self, xAdv, yMax, ySecond, inDist, outSlack, sample):
        self.xAdv = xAdv # Sample pertubing around.
        self.yMax = yMax # Highest prediction produced by the network.
        self.ySecond = ySecond # Second highest prediction produced by the network.
        self.inDist = inDist # Input pertubation distance.
        self.outSlack = outSlack # Slack allowed in the output (default value is 0)
        self.xAdvIndex = sample # Sample index in relevant dataset.

# Possible verification results enum.        
class Result(Enum):    
    LTIMEOUT = 0 # Local timeout - verification ended in in a query timeout.
    SAT = 1 # Verification ended with SAT.
    UNSAT = 2 # Verification ended with UNSAT.
    GTIMEOUT = 3 # Global timeout - verification ended in in a query timeout.
    SPURIOUS = 4 # Spurious CEX.
    ERROR = 5 # Error.

    @staticmethod
    def fromString(s):
        s = s.lower()
        if s == "ltimeout":
            return Result.LTIMEOUT
        elif s == "sat":
            return Result.SAT
        elif s == "unsat":
            return Result.UNSAT
        elif s == "gtimeout":
            return Result.GTIMEOUT
        elif s == "spurious":
            return Result.SPURIOUS
        elif s == "error":
            return Result.ERROR
        else:
            raise NotImplementedError            

# Verification result.        
class ResultObj:
    
    def __init__(self, result):
        self.originalQueryStats = None
        self.finalQueryStats = None
        self.cex = None
        self.cexPrediction = np.array([])
        self.result = Result.fromString(result)

    def isTimeout(self):
        return (self.result is Result.LTIMEOUT) or (self.result is Result.GTIMEOUT)

    def isSat(self):
        return self.result is Result.SAT
    
    def isUnsat(self):
        return self.result is Result.UNSAT
    
    def setStats(self, orig, final):
        self.originalQueryStats = orig
        self.finalQueryStats = final

    def setCex(self, cex, cexPrediction):
        self.cex = cex
        self.cexPrediction = cexPrediction

    def returnResult(self):
        CnnAbs.printLog("\n*******************************************************************************\n")
        CnnAbs.printLog("\n\nResult is:\n\n    {}\n\n".format(self.result.name))        
        return self.result.name, self.cex

# Used dataset, MNIST is implemented.
class DataSet:

    def __init__(self, ds='mnist'):
        if ds.lower() == 'mnist':
            self.setMnist()
        else:
            raise NotImplementedError

    # Read dataset from numpy file for offline use.
    @staticmethod
    def readFromFile(dataset):        
        with open('/'.join([CnnAbs.maraboupyPath, dataset, 'x_train.npy']), 'rb') as f:
            x_train = np.load(f, allow_pickle=True)
        with open('/'.join([CnnAbs.maraboupyPath, dataset, 'y_train.npy']), 'rb') as f:
            y_train = np.load(f, allow_pickle=True)
        with open('/'.join([CnnAbs.maraboupyPath, dataset, 'x_test.npy']), 'rb') as f:
            x_test = np.load(f, allow_pickle=True)
        with open('/'.join([CnnAbs.maraboupyPath, dataset, 'y_test.npy']), 'rb') as f:
            y_test = np.load(f, allow_pickle=True)            
        return (x_train, y_train), (x_test, y_test)
    
    def setMnist(self):
        self.num_classes = 10
        self.input_shape = (28,28,1)
        (self.x_train, self.y_train), (self.x_test, self.y_test) = DataSet.readFromFile('mnist')
        self.x_train, self.x_test = self.x_train / 255.0, self.x_test / 255.0
        self.x_train = np.expand_dims(self.x_train, -1)
        self.x_test = np.expand_dims(self.x_test, -1)
        self.featureShape=(1,28,28)
        self.loss='sparse_categorical_crossentropy'
        self.optimizer='adam'
        self.metrics=['accuracy']
        self.valueRange = (0,1) #Input pixels value range
        self.name = 'mnist'

# Custom loss object used while training the evaluated networks.        
def myLoss(labels, logits):
    return tf.keras.losses.sparse_categorical_crossentropy(labels, logits, from_logits=True)

# Implements utilities for the Tensorflow interface.
class ModelUtils:

    def __init__(self, ds, options, logDir):
        self.ds = ds
        self.options = options
        self.logDir = logDir

    #Format to my onnx saving format.
    @staticmethod
    def onnxNameFormat(m, suffix=""):
        if suffix:
            suffix = "_" + suffix
        return "./{}{}.onnx".format(m.name, suffix)

    # Translate Tensorflow Sequential to Marabou model.
    def tf2Model(self, model):
        modelOnnx = keras2onnx.convert_keras(model, model.name + "_onnx", debug_mode=0)
        modelOnnxName = ModelUtils.onnxNameFormat(model)
        keras2onnx.save_model(modelOnnx, self.logDir + modelOnnxName)
        return MarabouNetworkONNX.MarabouNetworkONNX(self.logDir + modelOnnxName)

    # Cut sequential model up to a certain layer.
    def modelUpToLayer(model, layerName):
        if layerName not in [l.name for l in model.layers]:
            layerName = list([l.name for l in reversed(model.layers) if l.name.startswith(layerName)])[0]
        return tf.keras.Model(inputs=model.input, outputs=model.get_layer(name=layerName).output)

    # Load saved model.
    def loadModel(self, path):
        model = load_model(os.path.abspath(path), custom_objects={'myLoss': myLoss})
        model.summary()
        score = model.evaluate(self.ds.x_test, self.ds.y_test, verbose=0)
        CnnAbs.printLog("(Original) Test loss:{}".format(score[0]))
        CnnAbs.printLog("(Original) Test accuracy:{}".format(score[1]))
        return model    

# Containing functions manipulating verification query, with specific implementation to used tool.    
class QueryUtils:

    # Set neurons with no incoming edges as inputs.
    @staticmethod
    def setUnconnectedAsInputs(model):        
        varsWithIngoingEdgesOrInputs = set([v.item() for nparr in model.inputVars for v in np.nditer(nparr, flags=["zerosize_ok"])])
        for eq in model.equList:
            if eq.EquationType == MarabouCore.Equation.EQ and eq.addendList[-1][0] == -1 and any([el[0] != 0 for el in eq.addendList[:-1]]):
                varsWithIngoingEdgesOrInputs.add(eq.addendList[-1][1])
        for peicewiseLinearConstraint in itertools.chain(model.maxList, model.reluList, model.signList, model.absList):
            varsWithIngoingEdgesOrInputs.add(peicewiseLinearConstraint[1])
        varsWithoutIngoingEdges = {v for v in range(model.numVars) if v not in varsWithIngoingEdgesOrInputs}
        assert all([model.lowerBoundExists(v) and model.upperBoundExists(v) for v in varsWithoutIngoingEdges])
        model.inputVars.append(np.array([v for v in varsWithoutIngoingEdges]))

    # Get division of the network to layers.
    @staticmethod        
    def divideToLayers(model):
        layerMappingReverse = dict()
        layer = set(model.outputVars.flatten().tolist())
        layerNum = 0
        lastMapped = 0
        nextLayerWas0 = False
        layerType = list()
        while len(layerMappingReverse) < model.numVars:
            nextLayer = set()
            for var in layer:
                assert var not in layerMappingReverse
                layerMappingReverse[var] = layerNum
            layerType.insert(0, set())
            for eq in model.equList:
                if (eq.addendList[-1][1] in layer) and (eq.EquationType == MarabouCore.Equation.EQ):
                    [nextLayer.add(el[1]) for el in eq.addendList[:-1] if el[0] != 0]
                    layerType[0].add("Linear")
            for maxArgs, maxOut in model.maxList:
                if maxOut in layer:
                    [nextLayer.add(arg) for arg in maxArgs]
                    layerType[0].add("Max")
            [(nextLayer.add(vin), layerType[0].add("Relu")) for vin,vout in model.reluList if vout in layer]
            [(nextLayer.add(vin), layerType[0].add("Abs"))  for vin,vout in model.absList  if vout in layer]
            [(nextLayer.add(vin), layerType[0].add("Sign")) for vin,vout in model.signList if vout in layer]
            if not layerType[0]:
                layerType[0].add("Input")
            layer = nextLayer
            assert not nextLayerWas0
            nextLayerWas0 = len(nextLayer) == 0
            layerNum += 1
        layerMapping = dict()
        for v,l in layerMappingReverse.items():
            layerMapping[v] = layerNum - l - 1
        assert all([i in layerMapping for i in model.inputVars[0].flatten().tolist()])
        layerList = [set() for i in range(layerNum)]
        [layerList[l].add(var) for var,l in layerMapping.items()]
        return layerList, layerType

    # Remove the variables of model that are not in the set variablesToKeep. If KeepInputShape==False, input shape is flatten.
    @staticmethod        
    def removeVariables(model, variablesToKeep, keepInputShape=False):
        assert len(set(variablesToKeep)) == len(variablesToKeep)        
        variablesToKeep = set(variablesToKeep)
        variablesToKeepList = list(variablesToKeep)
        variablesToKeepList.sort()
        tr = lambda v: variablesToKeepList.index(v) if v in variablesToKeepList else -1
        varsMapping = {tr(v) : v for v in range(model.numVars) if tr(v) != -1}
        
        for vin,vout in itertools.chain(model.reluList, model.signList, model.absList):
            assert (vin in variablesToKeep) == (vout in variablesToKeep)
    
        newEquList = list()
        for eq in model.equList:
            if (eq.EquationType == MarabouCore.Equation.EQ) and (eq.addendList[-1][0] == -1):
                newEq = MarabouUtils.Equation()
                newEq.scalar = eq.scalar
                newEq.EquationType = MarabouCore.Equation.EQ
                newEq.addendList = [(el[0],tr(el[1])) for el in eq.addendList if el[1] in variablesToKeep]
                if (eq.addendList[-1][1] not in variablesToKeep) or len(newEq.addendList) == 1:
                    continue
                if all([el[0] == 0 for el in eq.addendList[:-1]]):
                    continue
                if newEq.addendList:
                    newEquList.append(newEq)
            else:
                newEq = MarabouUtils.Equation()
                newEq.scalar = eq.scalar
                newEq.EquationType = eq.EquationType
                newEq.addendList = [(el[0],tr(el[1])) for el in eq.addendList]
                if all([v != -1 for (c, v) in newEq.addendList]):
                    newEquList.append(newEq)
        model.equList  = newEquList
        model.maxList  = [({tr(arg) for arg in maxArgs if arg in variablesToKeep}, tr(maxOut)) for maxArgs, maxOut in model.maxList if (maxOut in variablesToKeep and any([arg in variablesToKeep for arg in maxArgs]))]
        model.reluList = [(tr(vin),tr(vout)) for vin,vout in model.reluList if vout in variablesToKeep]
        model.absList  = [(tr(vin),tr(vout)) for vin,vout in model.absList  if vout in variablesToKeep]
        model.signList = [(tr(vin),tr(vout)) for vin,vout in model.signList if vout in variablesToKeep]
        model.lowerBounds = {tr(v):l for v,l in model.lowerBounds.items() if v in variablesToKeep}
        model.upperBounds = {tr(v):u for v,u in model.upperBounds.items() if v in variablesToKeep}
        inputVarsMapping = np.array([tr(v) for v in model.inputVars[0].flatten().tolist()]).reshape(model.inputVars[0].shape)
        outputVarsMapping = np.array([tr(v) for v in model.outputVars.flatten().tolist()]).reshape(model.outputVars.shape)
        if keepInputShape:
            assert all([v in variablesToKeep for inp in model.inputVars for v in inp.flatten().tolist()])
        else:
            model.inputVars  = [np.array([tr(v) for v in inp.flatten().tolist() if v in variablesToKeep]) for inp in model.inputVars]
        model.outputVars = np.array([tr(v) for v in model.outputVars.flatten().tolist() if v in variablesToKeep])
        model.numVars = len(variablesToKeepList)
        assert inputVarsMapping is not None and outputVarsMapping is not None
        return inputVarsMapping, outputVarsMapping, varsMapping

    # Prune (remove) neurons that do not reach the initialSet.
    @staticmethod
    def pruneUnreachableNeurons(model, initialSet):
        origNumVars = model.numVars
        reach = set(initialSet)
        lastLen = 0
        while len(reach) > lastLen:
            lastLen = len(reach)
            reachPrev = reach.copy()
            for eqi, eq in enumerate(model.equList):
                tw, tv = eq.addendList[-1]
                if (tv in reachPrev) and (tw == -1) and (eq.EquationType == MarabouCore.Equation.EQ):
                    [reach.add(v) for w,v in eq.addendList[:-1] if w != 0]
                elif (eq.EquationType != MarabouCore.Equation.EQ) or (eq.addendList[-1][0] != -1):
                    [reach.add(v) for w,v in eq.addendList]
            for maxArgs, maxOut in model.maxList:
                if maxOut in reachPrev:
                    [reach.add(arg) for arg in maxArgs]
            [reach.add(vin) for vin,vout in itertools.chain(model.reluList, model.signList, model.absList) if vout in reachPrev]
            if len(model.disjunctionList) > 0:
                raise NotImplementedError
        unreach = {v for v in range(model.numVars) if v not in reach}
        inputVarsMapping, outputVarsMapping, varsMapping = QueryUtils.removeVariables(model, reach)
        for eq in model.equList:
            for w,v in eq.addendList:
                if v > model.numVars:
                    CnnAbs.printLog("eq.addendList={}, eq.scalar={}, eq.EquationType={}".format(eq.addendList, eq.scalar, eq.EquationType))
        CnnAbs.printLog("Number of vars in abstract network out of original network = {}".format(model.numVars / float(origNumVars)))
        return inputVarsMapping, outputVarsMapping, varsMapping

    # Get pertubaition bounds according to infinity norm around a point.
    @staticmethod
    def getPertubationInftyBall(point, radius, floatingPointErrorGap=0, valueRange=None):
        assert floatingPointErrorGap >= 0
        if valueRange is not None:
            lower, upper = np.maximum(point - radius,np.full_like(point, valueRange[0])), np.minimum(point + radius,np.full_like(point, valueRange[1]))
        else:
            lower, upper = point - radius, point + radius
        assert np.all(upper - lower > 2 * floatingPointErrorGap)
        upper -= floatingPointErrorGap
        lower += floatingPointErrorGap
        return lower, upper

    # Check if otherPoint is in infinity-norm distance radius from point.
    @staticmethod
    def inBoundsInftyBall(point, radius, otherPoint, valueRange=None):
        assert otherPoint.shape == point.shape
        lower, upper = QueryUtils.getPertubationInftyBall(point, radius, valueRange=valueRange)
        geqLow = np.less_equal(lower, otherPoint)
        leqUp  = np.less_equal(otherPoint, upper)
        inBounds = np.logical_and(geqLow, leqUp)
        violations = np.logical_not(inBounds)
        assert violations.shape == point.shape
        return np.all(inBounds), violations

    # Set adversarial robustness query on model.
    @staticmethod
    def setAdversarial(model, point, inDist, outSlack, yMax, ySecond, valueRange=None):
        inputAsNumpyArray = np.array(model.inputVars[0])
        point = point.reshape(inputAsNumpyArray.shape)
        lower, upper = QueryUtils.getPertubationInftyBall(point, inDist, floatingPointErrorGap=0.0025, valueRange=valueRange)
        floatingPointErrorGapOutput = 0.03
        for i, l, u in zip(np.nditer(inputAsNumpyArray),np.nditer(lower),np.nditer(upper)):
            model.lowerBounds.pop(i.item(), None)
            model.upperBounds.pop(i.item(), None)
            model.setLowerBound(i.item(),l.item())
            model.setUpperBound(i.item(),u.item())
        for j,o in enumerate(np.nditer(np.array(model.outputVars))):
            if j == yMax:
                yMaxVar = o.item()
            if j == ySecond:
                ySecondVar = o.item()
        model.addInequality([yMaxVar, ySecondVar], [1,-1], outSlack - floatingPointErrorGapOutput) # yMax + floatingPointErrorGap <= ySecond + slack
        return model

    # Save Query.
    @staticmethod
    def saveQuery(ipq, path):
        return MarabouCore.saveQuery(ipq, path)

    # Solve Query.
    @staticmethod    
    def solveQuery(model, options, logDir):
        cwd = os.getcwd()        
        os.chdir(logDir)
        vals, stats = Marabou.solve_query(model.getMarabouQuery(), verbose=False, options=options)
        os.chdir(cwd)
        return vals, stats

    # Preprocess query, used to dump bounds.
    @staticmethod    
    def preprocessQuery(model, options, logDir):
        model.saveQuery(logDir + "processInputQuery")
        cwd = os.getcwd()
        os.chdir(logDir)
        ipq = MarabouCore.preprocess(model.getMarabouQuery(), options)
        os.chdir(cwd)
        return ipq            

    # Extract interesting statistics from query.
    @staticmethod
    def marabouNetworkStats(model):
        return {"numVars" : model.numVars,
                "numEquations" : len(model.equList),
                "numReluConstraints" : len(model.reluList),
                "numMaxConstraints" : len(model.maxList),
                "numAbsConstraints" : len(model.absList),
                "numSignConstraints" : len(model.signList),
                "numDisjunction" : len(model.disjunctionList),
                "numLowerBounds" : len(model.lowerBounds),
                "numUpperBounds" : len(model.upperBounds),
                "numInputVars" : sum([np.array(inputVars).size for inputVars in model.inputVars]),
                "numOutputVars" : model.outputVars.size}
    

#################################################################################################################
#################################################################################################################
#################################################################################################################
#################################################################################################################
#################################################################################################################
    

####   _____                      _
####  / ____|               /\   | |
#### | |     _ __  _ __    /  \  | |__  ___
#### | |    | '_ \| '_ \  / /\ \ | '_ \/ __|
#### | |____| | | | | | |/ ____ \| |_) \__ \
####  \_____|_| |_|_| |_/_/    \_\_.__/|___/
####                                        
                                        
# Class implementing the tool's solving and logging procedures.
class CnnAbs:

    logger = None
    basePath = os.getcwd()
    maraboupyPath = basePath.split('maraboupy', maxsplit=1)[0] + 'maraboupy'
    marabouPath = basePath.split('Marabou', maxsplit=1)[0] + 'Marabou'    
    resultsFile = 'Results'
    resultsFileBrief = 'ResultsBrief'
    
    def __init__(self, ds='mnist', options=None, logDir='', gtimeout=7200, policy=None, abstractFirst=False):
        options = Marabou.createOptions(**options)
        logDir = "/".join(filter(None, [CnnAbs.basePath, logDir]))
        self.ds = DataSet(ds)
        self.options = options
        self.logDir = logDir
        if not self.logDir.endswith("/"):
            self.logDir += "/"
        os.makedirs(self.logDir, exist_ok=True)
        if CnnAbs.logger == None:
            CnnAbs.setLogger(logDir=self.logDir)
        if os.path.exists(self.logDir + CnnAbs.resultsFile + ".json"):
            self.resultsJson = self.loadJson(CnnAbs.resultsFile, loadDir=self.logDir)
        else:
            self.resultsJson = dict(subResults=[])
        self.numSteps = None
        self.startTotal = time.time()
        self.gtimeout = gtimeout
        self.prevTimeStamp = time.time()
        self.policy = Policy.fromString(policy, self.ds.name)
        self.modelUtils = ModelUtils(self.ds, self.options, self.logDir)
        self.abstractFirst = abstractFirst

    def solveAdversarial(self, modelTF, policyName, sample, propDist, propSlack=0):
        if not self.tickGtimeout():
            return self.returnGtimeout()        
        policy = Policy.fromString(policyName, self.ds.name)
        xAdv = self.ds.x_test[sample]
        yAdv = self.ds.y_test[sample]
        yPredict = modelTF.predict(np.array([xAdv]))
        yMax = yPredict.argmax()
        yPredictNoMax = np.copy(yPredict)
        yPredictNoMax[0][yMax] = np.min(yPredict)
        ySecond = yPredictNoMax.argmax()
        if ySecond == yMax:
            ySecond = 0 if yMax > 0 else 1
            
        prop = AdversarialProperty(xAdv, yMax, ySecond, propDist, propSlack, sample)
        mbouModel = self.modelUtils.tf2Model(modelTF)
        QueryUtils.setAdversarial(mbouModel, xAdv, propDist, propSlack, yMax, ySecond, valueRange=self.ds.valueRange)        

        fName = "xAdv.png"
        CnnAbs.printLog("Printing original input to file {}, this is sample {} with label {}".format(fName, sample, yAdv))
        plt.figure()        
        plt.imshow(np.squeeze(xAdv), cmap='Greys')
        plt.colorbar()
        plt.title('Example {}. DataSet Label: {}, model Predicts {}'.format(sample, yAdv, yMax))
        plt.savefig(self.logDir + fName)
        with open(self.logDir + fName.replace("png","npy"), "wb") as f:
            np.save(f, xAdv)            
        self.resultsJson["yDataset"] = int(yAdv.item())
        self.resultsJson["yMaxPrediction"] = int(yMax)
        self.resultsJson["ySecondPrediction"] = int(ySecond)
        self.dumpResultsJson()
        if not self.tickGtimeout():
            return self.returnGtimeout()        
        return self.solve(mbouModel, modelTF, policy, prop, generalRunName="sample_{},policy_{},propDist_{}".format(sample, policyName, str(propDist).replace('.','-')))

    def solve(self, mbouModel, modelTF, policy, prop, generalRunName=""):
        startBoundTightening = time.time()
        if not self.tickGtimeout():
            return self.returnGtimeout()
        CnnAbs.printLog("Started dumping bounds - used for abstraction")
        ipq = self.propagateBounds(mbouModel)
        if not self.tickGtimeout():
            return self.returnGtimeout()        
        QueryUtils.saveQuery(ipq, self.logDir + "IPQ_dumpBounds")
        CnnAbs.printLog("Finished dumping bounds - used for abstraction")
        endBoundTightening = time.time()
        self.resultsJson["boundTighteningRuntime"] = endBoundTightening - startBoundTightening    
        if ipq.getNumberOfVariables() == 0:
            self.resultsJson["SAT"] = False
            self.resultsJson["Result"] = "UNSAT"
            self.resultsJson["successfulRuntime"] = endBoundTightening - startBoundTightening
            self.resultsJson["successfulRun"] = 0
            self.resultsJson["totalRuntime"] = time.time() - self.startTotal
            self.dumpResultsJson()
            CnnAbs.printLog("----- UNSAT on first LP bound tightening")
            return ResultObj("unsat").returnResult()
        else:
            os.rename(self.logDir + "dumpBounds.json", self.logDir + "dumpBoundsInitial.json") #This is to prevent accidental override of this file.
        if os.path.isfile(self.logDir + "dumpBoundsInitial.json"):
            boundList = self.loadJson("dumpBoundsInitial", loadDir=self.logDir)
            boundDict = {bound["variable"] : (bound["lower"], bound["upper"]) for bound in boundList}
        else:
            boundDict = None

        self.options._dumpBounds = False
        self.modelUtils.options._dumpBounds = False        
        originalQueryStats = self.dumpQueryStats(mbouModel, "originalQueryStats_" + generalRunName)        
        successful = None
        absRefineBatches = self.abstractionRefinementBatches(mbouModel, modelTF, policy, prop)
        self.numSteps = len(absRefineBatches)
        self.resultsJson["absRefineBatches"] = self.numSteps
        self.dumpResultsJson()

        CnnAbs.printLog("Abstraction-refinement steps up to full network = {}".format(len(absRefineBatches)))
        for i, abstractNeurons in enumerate(absRefineBatches):
            if self.isGlobalTimedOut():
                break
            mbouModelAbstract, inputVarsMapping, outputVarsMapping, varsMapping = self.abstractAndPrune(mbouModel, abstractNeurons, boundDict)
            if i+1 == len(absRefineBatches):
                self.options._timeoutInSeconds = 0
            runName = generalRunName + ",step_{}_outOf_{}".format(i, len(absRefineBatches)-1)
            if not self.tickGtimeout():
                return self.returnGtimeout()
            resultObj = self.runMarabou(mbouModelAbstract, prop, runName, inputVarsMapping=inputVarsMapping, outputVarsMapping=outputVarsMapping, varsMapping=varsMapping, modelTF=modelTF, originalQueryStats=originalQueryStats)
            if not self.tickGtimeout():
                return self.returnGtimeout()            
            if resultObj.isTimeout():
                continue
            if resultObj.isSat():
                try:
                    isSpurious = self.isCEXSpurious(modelTF, prop, resultObj.cex)
                except Exception as err:
                    CnnAbs.printLog(err)
                    isSpurious = True
                CnnAbs.printLog("Found {} CEX in step {}/{}.".format("spurious" if isSpurious else "real", i, len(absRefineBatches)-1))
                if not isSpurious:
                    successful = i
                    break
                elif i+1 == len(absRefineBatches):
                    resultObj = ResultObj("error")
                    break 
            elif resultObj.isUnsat():
                CnnAbs.printLog("Found UNSAT in step {}/{}.".format(i, len(absRefineBatches)-1))
                successful = i
                break
            else:
                raise NotImplementedError

            if not self.tickGtimeout():
                return self.returnGtimeout()
        globalTimeout = self.isGlobalTimedOut()    
        if globalTimeout:
            resultObj = ResultObj("gtimeout")
        success = not resultObj.isTimeout() and (successful is not None)
        if resultObj.isSat() and not success:
            resultObj = ResultObj("spurious")
    
        if success:
            CnnAbs.printLog("successful={}/{}".format(successful, self.numSteps-1)) if (successful+1) < self.numSteps else CnnAbs.printLog("successful=Full")
            self.resultsJson["successfulRuntime"] = self.resultsJson["subResults"][-1]["runtime"]
            self.resultsJson["successfulRun"] = successful + 1        
        self.resultsJson["totalRuntime"] = time.time() - self.startTotal
        self.resultsJson["SAT"] = resultObj.isSat()
        self.resultsJson["Result"] = resultObj.result.name
        self.dumpResultsJson()
        return resultObj.returnResult()
    

    def abstractionRefinementBatches(self, model, modelTF, policy, prop):
        if policy.policy is Policy.Vanilla:
            return [set()]
        layerList, layerTypes = QueryUtils.divideToLayers(model)
        assert all([len(t) == 1 for t in layerTypes])
        if self.abstractFirst:
            absLayer = next(i for i,t in enumerate(layerTypes) if 'Relu' in t)
            absLayerLayerName = 'c1'
        else:
            absLayer = [i for i,t in enumerate(layerTypes) if 'Max' in t][-1]
            absLayerLayerName = next(layer.name for layer in modelTF.layers[::-1] if isinstance(layer, tf.keras.layers.MaxPooling2D) or isinstance(layer, tf.keras.layers.MaxPooling1D))
        modelTFUpToAbsLayer = ModelUtils.modelUpToLayer(modelTF, absLayerLayerName)
        absLayerActivation = modelTFUpToAbsLayer.predict(self.ds.x_test)

        netPriorToAbsLayer = list(set().union(*layerList[:absLayer+1]))
        netPriorToAbsLayer.sort()
        modelUpToAbsLayer = copy.deepcopy(model)
        modelUpToAbsLayer.outputVars = np.sort(np.array(list(layerList[absLayer])))
        _ , _ , varsMapping = QueryUtils.removeVariables(modelUpToAbsLayer, netPriorToAbsLayer, keepInputShape=True)

        cwd = os.getcwd()
        os.chdir(self.logDir)        
        for j in random.sample(range(len(self.ds.x_test)), 10):
            tfout = absLayerActivation[j]
            mbouout = modelUpToAbsLayer.evaluate(self.ds.x_test[j])
            assert np.all( np.isclose(CnnAbs.flattenTF(tfout), mbouout, atol=1e-4) )
            assert np.all( np.isclose(tfout, CnnAbs.reshapeMbouOut(mbouout, tfout.shape), atol=1e-4 ) )
        os.chdir(cwd)
        
        absLayerRankAcsending = [varsMapping[v] for v in policy.rankAbsLayer(modelUpToAbsLayer, prop, absLayerActivation)]
        steps = list(policy.steps(len(absLayerRankAcsending)))
        batchSizes = [len(absLayerRankAcsending) - sum(steps[:i+1]) for i in range(len(steps))]
        return [set(absLayerRankAcsending[:batchSize]) for batchSize in batchSizes]

    @staticmethod
    def flattenTF(tfout):
        assert len(tfout.shape) == 3
        if tfout.shape[2] > 1:
            tfout = np.swapaxes(tfout, 0, 2)
            tfout = np.swapaxes(tfout, 1, 2)
        return tfout.flatten()

    @staticmethod    
    def reshapeMbouOut(mbouout, shape):
        assert len(shape) == 3        
        shape = np.roll(shape, 1)
        return np.swapaxes(np.swapaxes(mbouout.reshape(shape), 1, 2), 0, 2)
                
    def abstractAndPrune(self, model, abstractNeurons, boundDict):
        modelAbstract = copy.deepcopy(model)
        modelAbstract.equList  = [eq for eq in modelAbstract.equList  if eq.addendList[-1][1] not in abstractNeurons]
        modelAbstract.maxList  = [pw for pw in modelAbstract.maxList  if pw[1]                not in abstractNeurons]        
        modelAbstract.reluList = [pw for pw in modelAbstract.reluList if pw[1]                not in abstractNeurons]
        modelAbstract.absList  = [pw for pw in modelAbstract.absList  if pw[1]                not in abstractNeurons]
        modelAbstract.signList = [pw for pw in modelAbstract.signList if pw[1]                not in abstractNeurons]
        modelAbstract.inputVars.append(np.array(list(abstractNeurons)))
        for v in abstractNeurons:
            modelAbstract.setLowerBound(v, boundDict[v][0])
            modelAbstract.setUpperBound(v, boundDict[v][1])        
        inputVarsMapping, outputVarsMapping, varsMapping = QueryUtils.pruneUnreachableNeurons(modelAbstract, modelAbstract.outputVars.flatten().tolist())
        return modelAbstract, inputVarsMapping, outputVarsMapping, varsMapping

    def runMarabou(self, model, prop, runName="runMarabouOnKeras", inputVarsMapping=None, outputVarsMapping=None, varsMapping=None, modelTF=None, originalQueryStats=None):

        startLocal = time.time()    
        self.subResultAppend()
        finalQueryStats = self.dumpQueryStats(model, "finalQueryStats_" + runName)
        
        CnnAbs.printLog("----- Start Solving {}".format(runName))
        if self.options._timeoutInSeconds <= 0:
            self.options._timeoutInSeconds = self.gtimeout
        else:
            self.options._timeoutInSeconds = int(min(self.options._timeoutInSeconds, self.gtimeout))
        vals, stats = QueryUtils.solveQuery(model, self.options, self.logDir)
        CnnAbs.printLog("----- Finished Solving {}".format(runName))
        sat = len(vals) > 0
        timedOut = stats.hasTimedOut()
        if not sat:
            if timedOut:
                result = ResultObj("ltimeout")
                CnnAbs.printLog("----- Timed out (local) in {}".format(runName))
            else:
                result = ResultObj("unsat")
                CnnAbs.printLog("----- UNSAT in {}".format(runName))
        else:
            cex, cexPrediction = self.cexToImage(vals, prop, inputVarsMapping, outputVarsMapping)
            self.dumpCex(cex, cexPrediction, prop, runName, modelTF)
            result = ResultObj("sat")
            result.setCex(cex, cexPrediction)
            result.vals = vals
            result.varsMapping = varsMapping
            CnnAbs.printLog("----- SAT in {}".format(runName))
        result.setStats(originalQueryStats, finalQueryStats)            

        endLocal = time.time()
        self.subResultUpdate(runtime=endLocal-startLocal, runtimeTotal=time.time() - self.startTotal, sat=result.isSat(), timedOut=result.isTimeout(), originalQueryStats=originalQueryStats, finalQueryStats=finalQueryStats)
        if not self.tickGtimeout():
            return ResultObj("gtimeout")
        return result

    def propagateBounds(self, mbouModel):
        mbouModelCopy = copy.deepcopy(mbouModel)
        return QueryUtils.preprocessQuery(mbouModelCopy, self.options, self.logDir)

    def cexToImage(self, valDict, prop, inputVarsMapping=None, outputVarsMapping=None):
        lBounds = QueryUtils.getPertubationInftyBall(prop.xAdv, prop.inDist, valueRange=self.ds.valueRange)[0]
        assert all([indCOI.item() is not None for indCOI in np.nditer(np.array(inputVarsMapping), flags=["refs_ok"])])
        cex           = np.array([valDict[i.item()] if i.item() != -1 else lBnd for i,lBnd in zip(np.nditer(np.array(inputVarsMapping), flags=["refs_ok"]), np.nditer(lBounds))]).reshape(prop.xAdv.shape)
        cexPrediction = np.array([valDict[o.item()] if o.item() != -1 else 0 for o in np.nditer(np.array(outputVarsMapping), flags=["refs_ok"])]).reshape(outputVarsMapping.shape)
        return cex, cexPrediction

    def isCEXSpurious(self, model, prop, cex):
        inBounds, violations =  QueryUtils.inBoundsInftyBall(prop.xAdv, prop.inDist, cex, valueRange=self.ds.valueRange)
        if not inBounds:
            differences = cex - prop.xAdv
            if np.all(np.absolute(differences)[violations.nonzero()] <= np.full_like(differences[violations.nonzero()], 1e-10, dtype=np.double)):
                cex[violations.nonzero()] = prop.xAdv[violations.nonzero()]
        inBounds, violations =  QueryUtils.inBoundsInftyBall(prop.xAdv, prop.inDist, cex, valueRange=self.ds.valueRange)         
        if not inBounds:
            raise Exception("CEX out of bounds, violations={}, values={}, cex={}, prop.xAdv={}".format(np.transpose(violations.nonzero()), np.absolute(cex-prop.xAdv)[violations.nonzero()], cex[violations.nonzero()], prop.xAdv[violations.nonzero()]))
        prediction = model.predict(np.array([cex]))
        return prediction[0, prop.ySecond] + prop.outSlack < prediction[0, prop.yMax]
    
    def setGtimeout(self, val):
        if val <= 0:
            self.gtimeout = 1 #Because 0 is used in timeout to signal no timeout.
        else:
            self.gtimeout = int(val)

    def decGtimeout(self, val):
        self.setGtimeout(self.gtimeout - val)

    def tickGtimeout(self):
        currentTime = time.time()
        self.decGtimeout(currentTime - self.prevTimeStamp)
        self.prevTimeStamp = currentTime
        if self.isGlobalTimedOut():
            self.resultsJson["Result"] = "GTIMEOUT"
            self.resultsJson["totalRuntime"] = time.time() - self.startTotal
            self.dumpResultsJson()
            return False
        return True

    def isGlobalTimedOut(self):
        return self.gtimeout <= 1

    def returnGtimeout(self):        
        return ResultObj("gtimeout").returnResult()    

    def setLogger(suffix='', logDir=''):
        logging.basicConfig(level = logging.DEBUG, format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s", filename = logDir + 'cnnAbsTB{}.log'.format(suffix), filemode = "w")        
        CnnAbs.logger = logging.getLogger('cnnAbsTB{}'.format(suffix))
        logging.getLogger('matplotlib.font_manager').disabled = True
        
    @staticmethod
    def printLog(s):
        if CnnAbs.logger:
            CnnAbs.logger.info(s)
        print(s)

    def dumpCex(self, cex, cexPrediction, prop, runName, model):
        if model is not None:
            modelPrediction = model.predict(np.array([cex])).argmax()
        else:
            modelPrediction = None
        mbouPrediction = cexPrediction.argmax()
        plt.figure()
        plt.title('CEX, yMax={}, ySecond={}, MbouPredicts={}, modelPredicts={}'.format(prop.yMax, prop.ySecond, mbouPrediction, modelPrediction))
        plt.imshow(np.squeeze(cex), cmap='Greys')
        plt.colorbar()
        plt.savefig(self.logDir + "Cex_{}".format(runName) + ".png")
        self.dumpNpArray(cex, "Cex_{}".format(runName))        
        diff = np.abs(cex - prop.xAdv)
        plt.figure()
        plt.title('Distance between pixels: CEX and adv. sample')
        plt.imshow(np.squeeze(diff), cmap='Greys')
        plt.colorbar()
        plt.savefig(self.logDir + "DiffCexXAdv_{}".format(runName) + ".png")
        self.dumpNpArray(diff, "DiffCexXAdv_{}".format(runName))
        
    def dumpQueryStats(self, mbouNet, fileName):
        queryStats = QueryUtils.marabouNetworkStats(mbouNet)
        self.dumpJson(queryStats, fileName)
        return queryStats

    def dumpJson(self, data, fileName, saveDir=''):
        if not saveDir:
            saveDir = self.logDir
        if not saveDir.endswith("/"):
            saveDir += "/"            
        if not fileName.endswith(".json"):
            fileName += ".json"
        with open(saveDir + fileName, "w") as f:
            json.dump(data, f, indent = 4)
    
    # Load Json file from 
    def loadJson(self, fileName, loadDir=''):
        if not loadDir:
            loadDir = self.logDir
        if not fileName.endswith(".json"):
            fileName += ".json"
        if not loadDir.endswith("/"):
            loadDir += "/"
        with open(loadDir + fileName, "r") as f:
            return json.load(f)

    # Save Numpy array as .npy file.     
    def dumpNpArray(self, npArray, fileName, saveDir=''):
        if not saveDir:
            saveDir = self.logDir
        if not saveDir.endswith("/"):
            saveDir += "/"            
        if not fileName.endswith(".npy"):
            fileName += ".npy"
        with open(saveDir + fileName, "wb") as f:
            np.save(f, npArray)        

    # Load Numpy array from .npy file.
    def loadNpArray(self, fileName, loadDir=''):
        if not loadDir:
            loadDir = self.logDir
        if not fileName.endswith(".npy"):
            fileName += ".npy"
        if not loadDir.endswith("/"):
            loadDir += "/"
        with open(loadDir + fileName, "rb") as f:
            return np.load(f, allow_pickle=True)

    # Dump the resultJson data into Result.json file.
    def dumpResultsJson(self):
        self.dumpJson(self.resultsJson, CnnAbs.resultsFile)
        brief = dict()
        brief["Result"] = self.resultsJson["Result"] if "Result" in self.resultsJson else None
        brief["totalRuntime"] = self.resultsJson["totalRuntime"] if "totalRuntime" in self.resultsJson else None        
        self.dumpJson(brief, CnnAbs.resultsFileBrief)

    # Update run statistics in Result.json log (create new entry)    
    def subResultAppend(self, runtime=None, runtimeTotal=None, originalQueryStats=None, finalQueryStats=None, sat=None, timedOut=None):
        self.resultsJson["subResults"].append({"outOf" : self.numSteps-1,
                                               "runtime" : runtime,
                                               "runtimeTotal":runtimeTotal,
                                               "originalQueryStats" : originalQueryStats,
                                               "finalQueryStats" : finalQueryStats,
                                               "SAT" : sat,
                                               "timedOut" : timedOut})
        self.dumpResultsJson()

    # Update run statistics in Result.json log (update last entry)
    def subResultUpdate(self, runtime=None, runtimeTotal=None, originalQueryStats=None, finalQueryStats=None, sat=None, timedOut=None):
        self.resultsJson["subResults"][-1] = {"outOf" : self.numSteps-1,
                                              "runtime" : runtime,
                                              "runtimeTotal":runtimeTotal,
                                              "originalQueryStats" : originalQueryStats,
                                              "finalQueryStats" : finalQueryStats,
                                              "SAT" : sat,
                                              "timedOut" : timedOut}            
        self.dumpResultsJson()
