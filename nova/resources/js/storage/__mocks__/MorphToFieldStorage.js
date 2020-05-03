const resources = [{ value: 1 }, { value: 2 }, { value: 3 }]
const resourceTypes = {
    posts: true,
    videos: false,
}

export default {
    fetchAvailableResources(resourceName, fieldAttribute, { params }) {
        if (resourceName === undefined || fieldAttribute == undefined || params == undefined) {
            throw Error('please pass the right things')
        }

        return new Promise((resolve, reject) => {
            if (params.first == true) {
                // console.log('only the first one')
                // console.log(params.first, params.current, 'first == true')
                resolve({
                    data: {
                        resources: [resources[params.current - 1]],
                        withTrashed: true,
                        softDeletes: true,
                    },
                })
            } else {
                // console.log('loading all of them')
                resolve({
                    data: {
                        resources,
                        softDeletes: true,
                        withTrashed: true,
                    },
                })
            }
        })
    },

    determineIfSoftDeletes(resourceType) {
        return new Promise((resolve, reject) => {
            resolve({
                data: {
                    softDeletes: resourceTypes[resourceType],
                },
            })
        })
    },
}
